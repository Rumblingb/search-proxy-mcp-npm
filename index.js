#!/usr/bin/env node
// search-proxy-mcp — npm wrapper that spawns the Python MCP server
const { spawn } = require('child_process');
const path = require('path');

const serverPath = path.join(__dirname, 'server.py');
const child = spawn('python3', [serverPath], {
    stdio: 'inherit',
    env: { ...process.env }
});

child.on('error', (err) => {
    console.error('Failed to start search-proxy-mcp:', err.message);
    process.exit(1);
});

child.on('exit', (code) => process.exit(code || 0));
