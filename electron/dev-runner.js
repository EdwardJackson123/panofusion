// Simple dev runner — starts Electron pointing at Vite dev server
const { spawn } = require('child_process')
const path = require('path')

const electronPath = require('electron')
const electronMain = path.join(__dirname, 'main.js')

const child = spawn(electronPath, [electronMain, '--dev'], {
  stdio: 'inherit',
  env: { ...process.env, NODE_ENV: 'development' },
})

child.on('close', (code) => {
  process.exit(code)
})
