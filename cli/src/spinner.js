const FRAMES = ['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏'];
const INTERVAL = 80;

class Spinner {
  constructor({ color = '\x1b[33m', stream = process.stdout } = {}) {
    this._color = color;
    this._stream = stream;
    this._frameIdx = 0;
    this._timer = null;
    this._message = '';
  }

  start(message = '') {
    if (this._timer) return this;
    this._message = message;
    this._frameIdx = 0;
    this._render();
    this._timer = setInterval(() => this._render(), INTERVAL);
    return this;
  }

  update(message) {
    this._message = message;
    return this;
  }

  stop(finalMessage) {
    if (!this._timer) return;
    clearInterval(this._timer);
    this._timer = null;
    this._stream.write('\r\x1b[K');
    if (finalMessage) this._stream.write(finalMessage + '\n');
  }

  stopAndClear() {
    this.stop();
  }

  get active() {
    return this._timer !== null;
  }

  _render() {
    const frame = FRAMES[this._frameIdx % FRAMES.length];
    this._stream.write(`\r\x1b[K${this._color}${frame}\x1b[0m ${this._message}`);
    this._frameIdx++;
  }
}

function createThinkingSpinner() {
  return new Spinner({ color: '\x1b[33m' });
}

function createToolSpinner() {
  return new Spinner({ color: '\x1b[36m' });
}

export { Spinner, createThinkingSpinner, createToolSpinner };
