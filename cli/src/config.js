import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

const CONFIG_DIR = join(homedir(), '.reddy')
const CONFIG_FILE = join(CONFIG_DIR, 'config.json')

export const DEFAULT_CONFIG = {
  apiProvider: 'minimax',
  apiKey: '',
  baseUrl: 'https://api.minimaxi.com/anthropic/v1/messages',
  model: 'MiniMax-M2.7',
  temperature: 0.7,
  maxTokens: 2000,
  setupComplete: false,
}

export function loadConfig() {
  if (!existsSync(CONFIG_FILE)) {
    return { ...DEFAULT_CONFIG }
  }
  try {
    const content = readFileSync(CONFIG_FILE, 'utf-8')
    const config = JSON.parse(content)
    return { ...DEFAULT_CONFIG, ...config }
  } catch {
    return { ...DEFAULT_CONFIG }
  }
}

export function saveConfig(config) {
  try {
    if (!existsSync(CONFIG_DIR)) {
      mkdirSync(CONFIG_DIR, { recursive: true })
    }
    writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2))
    return true
  } catch {
    return false
  }
}

export function isConfigured() {
  const config = loadConfig()
  return config.setupComplete && config.apiKey && config.apiKey.length > 0
}

export function getConfigPath() {
  return CONFIG_FILE
}
