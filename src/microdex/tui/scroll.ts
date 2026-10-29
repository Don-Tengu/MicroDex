/** Normalize high-frequency touchpad events without throttling away slow wheel input. */
export class WheelNormalizer {
  private lastAt: number | undefined;
  private direction = 0;
  private rapidIntervals = 0;
  private trackpadBurst = false;
  private remainder = 0;

  consume(delta: -1 | 1, now = Date.now()): number {
    const direction = Math.sign(delta);
    const interval = this.lastAt === undefined ? undefined : now - this.lastAt;

    if (interval === undefined || interval > 120) {
      this.rapidIntervals = 0;
      this.trackpadBurst = false;
      this.remainder = 0;
    } else if (interval < 40) {
      this.rapidIntervals += 1;
      if (this.rapidIntervals >= 3) this.trackpadBurst = true;
    } else if (!this.trackpadBurst) {
      this.rapidIntervals = 0;
    }

    if (this.direction !== 0 && direction !== this.direction) this.remainder = 0;
    this.direction = direction;
    this.lastAt = now;

    if (!this.trackpadBurst) return delta;

    this.remainder += direction * 0.15;
    const lines = Math.trunc(this.remainder);
    this.remainder -= lines;
    return lines;
  }
}
