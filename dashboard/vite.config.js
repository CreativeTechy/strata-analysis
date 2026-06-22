import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend (FastAPI / main.py) base URL. Defaults to the local uvicorn server.
// In production set VITE_API_TARGET (or deploy the backend and proxy at the edge).
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/scrape': { target: API_TARGET, changeOrigin: true },
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
})
