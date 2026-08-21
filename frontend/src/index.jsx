import ReactDOM from 'react-dom/client'
import App from './App'

// StrictMode intentionally removed — it double-fires useEffect in dev mode,
// which causes Micdrop to initialise twice (two VADs, two mic streams,
// duplicate state events). This is the #1 cause of phantom speech detection.
ReactDOM.createRoot(document.getElementById('root')).render(<App />)
