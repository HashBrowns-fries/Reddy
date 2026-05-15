const AMBER = '\x1b[33m'
const CYAN = '\x1b[36m'
const MAGENTA = '\x1b[35m'
const DIM = '\x1b[90m'
export const RESET = '\x1b[0m'

export const REDDY_PIXEL = `
${AMBER}
██████╗ ███████╗██████╗ ██████╗ ██╗   ██╗
██╔══██╗██╔════╝██╔══██╗██╔══██╗╚██╗ ██╔╝
██████╔╝█████╗  ██║  ██║██║  ██║ ╚████╔╝
██╔══██╗██╔══╝  ██║  ██║██║  ██║  ╚██╔╝
██║  ██║███████╗██████╔╝██████╔╝   ██║
╚═╝  ╚═╝╚══════╝╚═════╝ ╚═════╝    ╚═╝
${RESET}`

export const REDDY_LOGO = REDDY_PIXEL

export const COLORS = {
  primary: '\x1b[33m',
  secondary: '\x1b[90m',
  background: '\x1b[0m',
  success: '\x1b[32m',
  error: '\x1b[31m',
  border: '\x1b[90m',
  text: '\x1b[37m',
  cyan: '\x1b[36m',
  magenta: '\x1b[35m',
}

export const HERMES = {
  thinking:  { color: '\x1b[33m', icon: '◆', label: '[Thinking]' },
  acting:    { color: '\x1b[36m', icon: '▶', label: '[Action]' },
  observing: { color: '\x1b[35m', icon: '◀', label: '[Observe]' },
  answer:    { color: '\x1b[32m', icon: '●', label: '[Answer]' },
  tool:      { color: '\x1b[90m', icon: '⚙', label: '[Tool]' },
  session:   { color: '\x1b[34m', icon: '═', label: '[Session]' },
}

export async function animateLogo() {
  const lines = REDDY_PIXEL.split('\n')
  for (const line of lines) {
    if (line.trim()) console.log(line)
    await new Promise(r => setTimeout(r, 50))
  }
}
