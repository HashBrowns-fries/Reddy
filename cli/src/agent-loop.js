import { spawn } from 'child_process'

let pythonProcess = null
let requestId = 0
let pendingRequests = new Map()
let buffer = ''
let eventListener = null

function handleLine(line) {
  if (!line.trim()) return
  try {
    const msg = JSON.parse(line)

    if (msg.type === 'agent_event') {
      if (eventListener) eventListener(msg.event)
      return
    }

    const resolver = pendingRequests.get(msg.id)
    if (resolver) {
      pendingRequests.delete(msg.id)
      resolver(msg)
    }
  } catch {}
}

function sendCommand(params, timeout = 120000) {
  return new Promise((resolve, reject) => {
    if (!pythonProcess) {
      reject(new Error('Backend not initialized'))
      return
    }

    const id = ++requestId
    const request = { ...params, id }
    pendingRequests.set(id, (response) => {
      if (response.success === false) {
        reject(new Error(response.error))
      } else {
        resolve(response)
      }
    })
    pythonProcess.stdin.write(JSON.stringify(request) + '\n')

    setTimeout(() => {
      if (pendingRequests.has(id)) {
        pendingRequests.delete(id)
        reject(new Error('Request timeout'))
      }
    }, timeout)
  })
}

export class AgentLoop {
  constructor(pythonCli, stdioCli, config = {}) {
    this.pythonCli = pythonCli
    this.stdioCli = stdioCli
    this.config = config
    this.messages = []
    this.tools = []
    this.hasLLM = false
    this._running = false
    this.sessionId = null
  }

  async init() {
    const env = {
      ...process.env,
      MINIMAX_API_KEY: this.config.apiKey || '',
      LLM_API: this.config.apiProvider || 'minimax',
    }
    pythonProcess = spawn(this.pythonCli, [this.stdioCli], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env,
    })

    pythonProcess.stdout.on('data', (data) => {
      buffer += data.toString()
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) handleLine(line)
    })

    pythonProcess.stderr.on('data', () => {})
    pythonProcess.on('error', () => {})
    pythonProcess.on('close', () => {
      pythonProcess = null
      for (const [id, resolver] of pendingRequests) {
        resolver({ success: false, error: 'Backend process closed' })
      }
      pendingRequests.clear()
    })

    const info = await sendCommand({ cmd: 'init' })
    this.hasLLM = info.has_llm
    this.tools = info.tools || []
    return this
  }

  async ensureRunning() {
    if (!pythonProcess || pythonProcess.killed) {
      await this.init()
    }
  }

  async run(userInput, onEvent) {
    if (this._running) {
      throw new Error('Agent is already processing')
    }
    this._running = true

    try {
      await this.ensureRunning()

      if (!this.hasLLM) {
        return { type: 'error', content: 'LLM not configured. Run "reddy config".' }
      }

      eventListener = onEvent || null

      const response = await sendCommand(
        {
          cmd: 'run',
          params: { message: userInput, session_id: this.sessionId },
          stream: !!onEvent,
        },
        180000,
      )

      eventListener = null
      return { type: 'text', content: response.result }
    } catch (error) {
      eventListener = null
      return { type: 'error', content: error.message }
    } finally {
      this._running = false
    }
  }

  async listTools() {
    try {
      await this.ensureRunning()
      const info = await sendCommand({ cmd: 'list_tools' })
      return info.tools || []
    } catch {
      return []
    }
  }

  async dispatchTool(name, args) {
    try {
      await this.ensureRunning()
      const info = await sendCommand({ cmd: 'dispatch', params: { name, args } })
      return info.result
    } catch (error) {
      return { error: error.message }
    }
  }

  close() {
    if (pythonProcess) {
      pythonProcess.kill()
      pythonProcess = null
    }
  }
}

export async function createAgent(pythonCli, stdioCli, config = {}) {
  const agent = new AgentLoop(pythonCli, stdioCli, config)
  await agent.init()
  return agent
}
