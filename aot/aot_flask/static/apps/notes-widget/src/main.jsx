import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

console.log("[AoT Notes] Bootstrapping React Widget...");
const rootElement = document.getElementById('aot-notes-widget-root');
console.log("[AoT Notes] Root Element:", rootElement);

if (rootElement) {
    createRoot(rootElement).render(
      <App />,
    )
} else {
    console.error("[AoT Notes] Target root element not found!");
}
