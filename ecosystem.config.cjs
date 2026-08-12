const path = require('node:path')

const root = __dirname
const appPort = process.env.APP_PORT || '8007'

module.exports = {
  apps: [
    {
      name: 'prizepass-api',
      cwd: path.join(root, 'backend'),
      script: path.join(root, '.venv/bin/uvicorn'),
      args: `app.main:app --host 127.0.0.1 --port ${appPort}`,
      instances: 1,
      autorestart: true,
      out_file: path.join(root, 'logs/api-out.log'),
      error_file: path.join(root, 'logs/api-error.log'),
    },
    {
      name: 'prizepass-worker',
      cwd: path.join(root, 'backend'),
      script: path.join(root, '.venv/bin/python'),
      args: '-m app.worker',
      instances: 1,
      autorestart: true,
      out_file: path.join(root, 'logs/worker-out.log'),
      error_file: path.join(root, 'logs/worker-error.log'),
    },
  ],
}
