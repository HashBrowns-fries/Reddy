import readline from 'readline'
import { loadConfig, saveConfig, DEFAULT_CONFIG, getConfigPath } from './config.js'
import { REDDY_LOGO, COLORS } from './logo.js'

export async function runSetup() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  })

  console.clear()
  console.log(REDDY_LOGO)

  console.log('\n\x1b[33m⚠  First-time setup required\x1b[0m\n')
  console.log('Please provide the following to configure Reddy:\n')

  const config = { ...DEFAULT_CONFIG }

  // API Provider
  const provider = await ask(rl, 'API Provider (1: MiniMax, 2: DeepSeek) [1]: ', '1')
  if (provider === '2') {
    config.apiProvider = 'deepseek'
    config.baseUrl = 'https://api.deepseek.com/v1'
    config.model = 'deepseek-chat'
  }

  // API Key
  const apiKey = await ask(rl, 'API Key: ', '')
  if (!apiKey || apiKey.length < 10) {
    console.log('\n\x1b[31m✗ Invalid API Key. Config saved but needs to be reconfigured\x1b[0m')
    config.setupComplete = false
    rl.close()
    return config
  }
  config.apiKey = apiKey

  // Model (optional)
  const model = await ask(rl, `Model [${config.model}]: `, '')
  if (model) config.model = model

  // Temperature
  const temp = await ask(rl, `Temperature [${config.temperature}]: `, '')
  if (temp && !isNaN(parseFloat(temp))) config.temperature = parseFloat(temp)

  // Max Tokens
  const tokens = await ask(rl, `Max Tokens [${config.maxTokens}]: `, '')
  if (tokens && !isNaN(parseInt(tokens))) config.maxTokens = parseInt(tokens)

  // OCR Setup
  console.log('\n\x1b[36m--- OCR Setup (optional) ---\x1b[0m\n')
  console.log('Umi-OCR: git clone https://github.com/hiroi-sora/Umi-OCR')
  console.log('Run: python wuyou_ocr_server.py (default port 1224)')

  const ocrUrl = await ask(rl, `OCR URL [http://127.0.0.1:1224/api/ocr]: `, '')
  config.ocrUrl = ocrUrl || 'http://127.0.0.1:1224/api/ocr'

  config.setupComplete = true

  rl.output.write('\n')
  rl.close()

  return config
}

export async function runConfigure() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  })

  console.clear()
  console.log(REDDY_LOGO)

  console.log('\n\x1b[36m  Configure Reddy\x1b[0m\n')
  console.log('Config file: ' + getConfigPath() + '\n')

  const current = loadConfig()
  const config = { ...current }

  // API Key
  const apiKey = await ask(rl, `API Key [***]: `, '')
  if (apiKey) config.apiKey = apiKey

  // Model
  const model = await ask(rl, `Model [${current.model}]: `, '')
  if (model) config.model = model

  // Temperature
  const temp = await ask(rl, `Temperature [${current.temperature}]: `, '')
  if (temp && !isNaN(parseFloat(temp))) config.temperature = parseFloat(temp)

  // Max Tokens
  const tokens = await ask(rl, `Max Tokens [${current.maxTokens}]: `, '')
  if (tokens && !isNaN(parseInt(tokens))) config.maxTokens = parseInt(tokens)

  // OCR
  const ocrUrl = await ask(rl, `OCR URL [${current.ocrUrl || 'http://127.0.0.1:1224/api/ocr'}]: `, '')
  if (ocrUrl) config.ocrUrl = ocrUrl

  rl.output.write('\n')
  rl.close()

  return config
}

export async function showConfig() {
  const config = loadConfig()
  console.log('\n\x1b[36m  Current Configuration\x1b[0m\n')
  console.log('  Provider:    ' + config.apiProvider)
  console.log('  API URL:     ' + config.baseUrl)
  console.log('  Model:       ' + config.model)
  console.log('  Temperature: ' + config.temperature)
  console.log('  Max Tokens:  ' + config.maxTokens)
  console.log('  OCR URL:     ' + (config.ocrUrl || 'Not configured'))
  console.log('  Configured:  ' + (config.setupComplete ? '\x1b[32mYes\x1b[0m' : '\x1b[31mNo\x1b[0m'))
  console.log('  Config file: ' + getConfigPath())
  console.log('')
}

function ask(rl, question, defaultVal) {
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      resolve(answer.trim() || defaultVal)
    })
  })
}
