// 16 section 2r item 4: the microphone is gathered on the audio thread instead
// of the page's main thread. At the booth that main thread also runs face
// detection every 400 ms, and in Rehman's C1 test a busy one could delay or
// drop microphone audio -- once badly enough that his name and confirmation
// never reached THE HOST at all.
//
// This processor does no arithmetic on the audio. It only gathers the 128-sample
// quanta the audio thread delivers into one block of the size the page asks
// for, and posts that block across. The level and the downsampler stay in
// audio.js exactly as they were, so what reaches the backend is unchanged.
//
// Chrome is the only browser at the booth, so there is no fallback here.

class MicCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    // The page sends the number of input samples that its downsampler needs to
    // produce one frame of 1600 samples at 16 kHz, which depends on the capture
    // device's own rate.
    this.blockSamples = options.processorOptions.blockSamples;
    this.block = new Float32Array(this.blockSamples);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    // A disconnected or not-yet-flowing input is not an error: keep the
    // processor alive and wait for the next quantum.
    if (!channel) return true;

    let offset = 0;
    while (offset < channel.length) {
      const room = this.blockSamples - this.filled;
      const take = Math.min(room, channel.length - offset);
      this.block.set(channel.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;
      if (this.filled === this.blockSamples) {
        // A copy is posted so the next quantum cannot overwrite a block that
        // is still in flight to the page.
        this.port.postMessage(this.block.slice(0));
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("mic-capture", MicCapture);
