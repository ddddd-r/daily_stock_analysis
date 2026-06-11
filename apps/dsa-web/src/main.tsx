import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { startTraditionalize } from './utils/traditionalize'

// 显示层简繁转换:整个界面(含 AI 报告/后端内容)即时显示为繁体(香港标准)
startTraditionalize()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
