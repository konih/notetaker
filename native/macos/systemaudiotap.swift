// systemaudiotap — capture macOS system (output) audio without a virtual driver.
//
// Uses Core Audio *process taps* (macOS 14.4+): a global tap over all system output is
// wrapped in a private aggregate device, and an IO proc block copies the delivered PCM to
// a file. This is the driver-free "BlackHole alternative" — no kext, no HAL plugin.
//
// Output: raw interleaved PCM in the tap's native format (typically 32-bit float, 48 kHz,
// stereo) written to the path given by `--out`; the tap's format is printed to stderr as
// `rate=<hz> ch=<n> float=<0|1>` so the caller can hand the raw stream to ffmpeg for
// resampling/mixdown into a WAV chunk. During pure silence the tap delivers no buffers, so
// the file may be empty (0 bytes) — the caller pads such chunks with silence.
//
// `muteBehavior = .unmuted` keeps the audio audible on the user's speakers while it is tapped.
//
// Permission: reading real audio (not silence) requires the "System Audio Recording Only"
// TCC grant (`kTCCServiceAudioCapture`). That prompt only fires for a *code-signed* binary
// carrying an `NSAudioCaptureUsageDescription` Info.plist string — see native/macos/README.md
// for the swiftc build + `codesign` steps (the Python adapter automates them).
//
// Usage: systemaudiotap --out <path> --seconds <float>

import AudioToolbox
import CoreAudio
import Foundation

func warn(_ message: String) {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
}

func die(_ message: String) -> Never {
    warn("systemaudiotap: " + message)
    exit(1)
}

func arg(_ name: String, default def: String) -> String {
    let args = CommandLine.arguments
    if let i = args.firstIndex(of: name), i + 1 < args.count {
        return args[i + 1]
    }
    return def
}

let outPath = arg("--out", default: "")
let seconds = Double(arg("--seconds", default: "10")) ?? 10.0
if outPath.isEmpty {
    die("--out <path> is required")
}

// 1. Global system tap, unmuted so the user still hears the meeting.
let tapDescription = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tapDescription.muteBehavior = .unmuted
var tapID = AudioObjectID(kAudioObjectUnknown)
if AudioHardwareCreateProcessTap(tapDescription, &tapID) != noErr {
    die("failed to create process tap (needs macOS 14.4+)")
}

// 2. Read the tap's UID (needed by the aggregate device) and stream format.
var uidAddress = AudioObjectPropertyAddress(
    mSelector: kAudioTapPropertyUID,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain,
)
var uidSize = UInt32(MemoryLayout<CFString?>.size)
var uidRef: Unmanaged<CFString>?
if AudioObjectGetPropertyData(tapID, &uidAddress, 0, nil, &uidSize, &uidRef) != noErr {
    die("failed to read tap UID")
}
let tapUID = uidRef!.takeRetainedValue()

var formatAddress = AudioObjectPropertyAddress(
    mSelector: kAudioTapPropertyFormat,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain,
)
var asbd = AudioStreamBasicDescription()
var asbdSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
if AudioObjectGetPropertyData(tapID, &formatAddress, 0, nil, &asbdSize, &asbd) != noErr {
    die("failed to read tap format")
}
let isFloat = (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0
warn("rate=\(asbd.mSampleRate) ch=\(asbd.mChannelsPerFrame) float=\(isFloat ? 1 : 0)")

// 3. Private aggregate device that auto-starts the tap.
let aggregateUID = "com.notetaker.systemtap.\(getpid())"
let aggregateDescription: [String: Any] = [
    kAudioAggregateDeviceUIDKey as String: aggregateUID,
    kAudioAggregateDeviceNameKey as String: "Notetaker System Tap",
    kAudioAggregateDeviceIsPrivateKey as String: true,
    kAudioAggregateDeviceIsStackedKey as String: false,
    kAudioAggregateDeviceTapAutoStartKey as String: true,
    kAudioAggregateDeviceTapListKey as String: [
        [
            kAudioSubTapUIDKey as String: tapUID,
            kAudioSubTapDriftCompensationKey as String: true,
        ]
    ],
]
var aggregateID = AudioObjectID(kAudioObjectUnknown)
if AudioHardwareCreateAggregateDevice(aggregateDescription as CFDictionary, &aggregateID) != noErr {
    die("failed to create aggregate device")
}

// 4. IO proc: copy delivered PCM straight to the output file.
FileManager.default.createFile(atPath: outPath, contents: nil)
guard let outFile = FileHandle(forWritingAtPath: outPath) else {
    die("failed to open output file: \(outPath)")
}

var ioProcID: AudioDeviceIOProcID?
let createStatus = AudioDeviceCreateIOProcIDWithBlock(&ioProcID, aggregateID, nil) {
    _, inputData, _, _, _ in
    let buffers = UnsafeMutableAudioBufferListPointer(
        UnsafeMutablePointer(mutating: inputData))
    for buffer in buffers {
        if let data = buffer.mData, buffer.mDataByteSize > 0 {
            outFile.write(Data(bytes: data, count: Int(buffer.mDataByteSize)))
        }
    }
}
if createStatus != noErr {
    die("failed to create IO proc")
}
if AudioDeviceStart(aggregateID, ioProcID) != noErr {
    die("failed to start capture")
}

RunLoop.current.run(until: Date().addingTimeInterval(seconds))

// 5. Tear down.
AudioDeviceStop(aggregateID, ioProcID)
if let procID = ioProcID {
    AudioDeviceDestroyIOProcID(aggregateID, procID)
}
AudioHardwareDestroyAggregateDevice(aggregateID)
AudioHardwareDestroyProcessTap(tapID)
try? outFile.close()
