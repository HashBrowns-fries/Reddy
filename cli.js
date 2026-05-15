#!/usr/bin/env node

import readline from 'readline'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import { existsSync, writeFileSync, readdirSync, readFileSync } from 'fs'
import { platform, homedir } from 'os'
import { loadConfig, saveConfig, isConfigured } from './cli/src/config.js'
import { runSetup, runConfigure, showConfig } from './cli/src/setup.js'
import { createAgent } from './cli/src/agent-loop.js'
import { COLORS, HERMES, RESET, animateLogo } from './cli/src/logo.js'
import { createThinkingSpinner, createToolSpinner } from './cli/src/spinner.js'

// ============== Portable path resolution ==============

function getProjectRoot() {
  return dirname(fileURLToPath(import.meta.url))
}

function findPython() {
  if (process.env.REDDY_PYTHON) return process.env.REDDY_PYTHON
  const root = getProjectRoot()
  const isWin = platform() === 'win32'
  const paths = isWin
    ? [join(root, '.venv', 'Scripts', 'python.exe')]
    : [join(root, '.venv', 'bin', 'python3'), join(root, '.venv', 'bin', 'python')]
  for (const p of paths) {
    if (existsSync(p)) return p
  }
  return isWin ? 'python' : 'python3'
}

const PYTHON_CLI = findPython()
const REDDY_STDIO = join(getProjectRoot(), 'redclaw', 'stdio_cli.py')

// ============== State ==============

let agent = null
let exiting = false
let chatHistory = []

// ============== Hermes display helpers ==============

const R = RESET
const line_thin = `${COLORS.secondary}${'─'.repeat(44)}${R}`
const line_thick = `${COLORS.secondary}${'═'.repeat(44)}${R}`

function truncate(s, max = 120) {
  if (!s) return ''
  const t = typeof s === 'string' ? s : JSON.stringify(s)
  return t.length > max ? t.slice(0, max) + '...' : t
}

// ============== Main ==============

async function main() {
  console.clear()
  await animateLogo()

  if (!isConfigured()) {
    console.log(`\n${COLORS.primary}  First-time setup required${R}\n`)
    const config = await runSetup()
    saveConfig(config)
    if (config.setupComplete) {
      console.log(`${COLORS.success}  Configuration saved${R}\n`)
    } else {
      console.log(`${COLORS.primary}  Setup incomplete. Please re-run reddy${R}\n`)
      process.exit(0)
    }
  }

  const config = loadConfig()

  try {
    agent = await createAgent(PYTHON_CLI, REDDY_STDIO, config)
  } catch (e) {
    console.error(`${COLORS.error}  Cannot connect to backend: ${e.message}${R}`)
    process.exit(1)
  }

  console.log(`\n${COLORS.success}  Ready${R}  ${COLORS.secondary}${agent.tools.length} tools loaded  |  Type help for commands${R}\n`)

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: `${COLORS.cyan}❯${R} `,
  })

  // ============== Commands ==============

  const commands = {
    help: () => {
      console.log(`
${line_thick}
${COLORS.cyan}  Reddy CLI Commands${R}
${line_thick}

  ${COLORS.primary}help${R}            Show this help
  ${COLORS.primary}config${R}          Configure API key and settings
  ${COLORS.primary}show${R}            Show current config
  ${COLORS.primary}exit${R}            Exit

${COLORS.cyan}  Chat Commands${R}

  ${COLORS.primary}/tools list${R}     List all available tools
  ${COLORS.primary}/tools call${R}     Call a tool directly <name> <json>
  ${COLORS.primary}/reset${R}          Reset session
  ${COLORS.primary}/history${R}        Show chat history
  ${COLORS.primary}/session${R}        Show past sessions
  ${COLORS.primary}/export${R}         Export chat history

${line_thin}
`)
    },

    config: async () => {
      const newConfig = await runConfigure()
      saveConfig(newConfig)
      console.log(`${COLORS.success}  Configuration saved${R}\n`)
    },

    show: () => showConfig(),

    tools: async (args) => {
      if (args === 'list') {
        const tools = await agent.listTools()
        console.log(`\n${COLORS.cyan}  Tools${R}  (${tools.length})\n`)
        for (const t of tools) {
          const tool = t.function || t
          console.log(`  ${COLORS.primary}${tool.name}${R}`)
          console.log(`    ${COLORS.secondary}${tool.description}${R}`)
        }
        console.log('')
      } else if (args && args.startsWith('call ')) {
        const parts = args.slice(5).match(/(\S+)\s+(.*)/)
        if (parts) {
          const [, name, argsStr] = parts
          let argsObj = {}
          try { argsObj = JSON.parse(argsStr) } catch {}
          const result = await agent.dispatchTool(name, argsObj)
          console.log(`\n${HERMES.observing.color}${HERMES.observing.label}${R}\n`)
          console.log(JSON.stringify(result, null, 2))
          console.log('')
        }
      } else {
        console.log(`${COLORS.secondary}  Usage: /tools list | /tools call <name> <json>${R}\n`)
      }
    },

    exit: () => {
      exiting = true
      if (agent) agent.close()
      console.log(`\n${COLORS.cyan}  Goodbye${R}\n`)
      process.exit(0)
    },

    reset: () => {
      chatHistory = []
      console.log(`${COLORS.success}  Session reset${R}\n`)
    },

    history: () => {
      if (chatHistory.length === 0) {
        console.log(`\n${COLORS.secondary}  No chat history yet${R}\n`)
        return
      }
      console.log(`\n${COLORS.cyan}  Chat History${R}\n`)
      for (const msg of chatHistory) {
        const color = msg.role === 'user' ? COLORS.primary : COLORS.cyan
        const label = msg.role === 'user' ? 'You' : 'Reddy'
        console.log(`  ${color}[${label}]${R} ${msg.content.split('\n')[0]}`)
      }
      console.log('')
    },

    session: () => {
      const memDir = join(homedir(), '.reddy', 'memory')
      if (!existsSync(memDir)) {
        console.log(`\n${COLORS.secondary}  No past sessions${R}\n`)
        return
      }
      const files = readdirSync(memDir).filter(f => f.startsWith('session_') && f.endsWith('.json'))
      if (files.length === 0) {
        console.log(`\n${COLORS.secondary}  No past sessions${R}\n`)
        return
      }
      console.log(`\n${COLORS.cyan}  Past Sessions${R}\n`)
      for (const f of files.sort().reverse().slice(0, 10)) {
        try {
          const data = JSON.parse(readFileSync(join(memDir, f), 'utf-8'))
          const sid = data.session_id || f.replace('session_', '').replace('.json', '')
          const turns = data.turns || (data.messages ? Math.floor(data.messages.length / 2) : '?')
          console.log(`  ${HERMES.session.color}${sid}${R}  ${COLORS.secondary}${turns} turns${R}`)
        } catch {}
      }
      console.log('')
    },

    export: () => {
      if (chatHistory.length === 0) {
        console.log(`\n${COLORS.secondary}  No chat history to export${R}\n`)
        return
      }
      const md = ['# Reddy Chat History\n']
      for (const msg of chatHistory) {
        md.push(`## ${msg.role.toUpperCase()}`)
        md.push(msg.content)
        md.push('')
      }
      const file = `reddy-export-${Date.now()}.md`
      writeFileSync(file, md.join('\n'))
      console.log(`${COLORS.success}  Exported to ${file}${R}\n`)
    },
  }

  // ============== SIGINT ==============

  process.on('SIGINT', () => {
    if (agent) agent.close()
    console.log(`\n${COLORS.cyan}  Goodbye${R}\n`)
    process.exit(0)
  })

  // ============== Input handler ==============

  rl.on('close', () => {
    if (!exiting) {
      if (agent) agent.close()
      console.log(`\n${COLORS.cyan}  Goodbye${R}\n`)
    }
  })

  rl.on('line', async (input) => {
    const line = (input || '').trim()
    if (!line) {
      if (!rl.closed) rl.prompt()
      return
    }

    // Slash commands
    if (line.startsWith('/')) {
      const cmd = line.slice(1).split(' ')[0]
      const args = line.slice(1).split(' ').slice(1).join(' ')
      if (commands[cmd]) {
        await commands[cmd](args)
      } else {
        console.log(`${COLORS.error}  Unknown command: ${cmd}${R}  Type help for available commands\n`)
      }
      if (!rl.closed) rl.prompt()
      return
    }

    // Plain text commands
    if (commands[line]) {
      await commands[line]()
      if (!rl.closed) rl.prompt()
      return
    }

    // ============== Hermes Agent Interaction ==============

    chatHistory.push({ role: 'user', content: line, timestamp: new Date() })

    console.log('')
    console.log(line_thick)
    console.log(`${HERMES.session.color}${HERMES.session.label}${R}  Model: ${COLORS.secondary}${config.model}${R}  Tools: ${COLORS.secondary}${agent.tools.length}${R}`)
    console.log(line_thick)

    let toolCount = 0
    let phase = null
    let spinner = null

    const stopSpinner = () => {
      if (spinner) { spinner.stopAndClear(); spinner = null }
    }

    try {
      const response = await agent.run(line, (event) => {
        switch (event.type) {
          case 'thinking':
            if (phase !== 'thinking') {
              stopSpinner()
              phase = 'thinking'
              spinner = createThinkingSpinner()
              spinner.start(`${HERMES.thinking.label}`)
            }
            break

          case 'tool_call':
            stopSpinner()
            phase = 'acting'
            toolCount++
            console.log(`\n${HERMES.acting.color}${HERMES.acting.icon} ${HERMES.acting.label}${R} ${COLORS.cyan}${event.name}${R}`)
            if (event.args && Object.keys(event.args).length > 0) {
              console.log(`  ${COLORS.secondary}${truncate(JSON.stringify(event.args), 100)}${R}`)
            }
            spinner = createToolSpinner()
            spinner.start(`${event.name}`)
            break

          case 'tool_result':
            stopSpinner()
            phase = 'observing'
            console.log(`${HERMES.observing.color}${HERMES.observing.icon} ${HERMES.observing.label}${R} ${COLORS.secondary}${truncate(event.result)}${R}`)
            break

          case 'text_done':
            stopSpinner()
            phase = 'answer'
            console.log(`\n${HERMES.answer.color}${HERMES.answer.icon} ${HERMES.answer.label}${R}`)
            console.log(`${COLORS.cyan}${event.text}${R}`)
            break

          case 'error':
            stopSpinner()
            console.log(`\n${COLORS.error}  ${event.message}${R}`)
            break
        }
      })

      stopSpinner()

      // Fallback: if no text_done event was emitted, print the response
      if (phase !== 'answer' && response.type === 'text' && response.content) {
        console.log(`\n${HERMES.answer.color}${HERMES.answer.icon} ${HERMES.answer.label}${R}`)
        console.log(`${COLORS.cyan}${response.content}${R}`)
      }

      if (response.type === 'error') {
        console.log(`\n${COLORS.error}  ${response.content}${R}`)
      } else if (response.content) {
        chatHistory.push({ role: 'assistant', content: response.content, timestamp: new Date() })
      }

      console.log('')
      console.log(line_thin)
      console.log(`${HERMES.session.color}${HERMES.session.label}${R}  Done  ${COLORS.secondary}Tools: ${toolCount}${R}`)
      console.log(line_thin)
      console.log('')

    } catch (error) {
      stopSpinner()
      console.log(`\n${COLORS.error}  ${error.message}${R}\n`)
    }

    if (!rl.closed) rl.prompt()
  })

  rl.prompt()
}

main().catch((e) => {
  console.error(`${COLORS.error}  Error: ${e.message}${R}`)
  process.exit(1)
})
