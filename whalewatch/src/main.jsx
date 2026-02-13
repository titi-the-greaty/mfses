import React from 'react'
import ReactDOM from 'react-dom/client'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error: error }
  }
  render() {
    if (this.state.error) {
      return React.createElement('pre', {
        style: { color: '#ff3366', background: '#0a0e14', padding: 20, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }
      }, 'WHALEWATCH CRASH:\n\n' + this.state.error.toString() + '\n\n' + (this.state.error.stack || ''))
    }
    return this.props.children
  }
}

async function mount() {
  try {
    var mod = await import('./App.jsx')
    var App = mod.default
    var root = ReactDOM.createRoot(document.getElementById('root'))
    root.render(
      React.createElement(ErrorBoundary, null,
        React.createElement(App)
      )
    )
  } catch (err) {
    document.getElementById('root').innerHTML =
      '<pre style="color:#ff3366;background:#0a0e14;padding:20px;font-family:monospace;white-space:pre-wrap">' +
      'WHALEWATCH MODULE CRASH:\n\n' + err.toString() + '\n\n' + (err.stack || '') +
      '\n\nThis error occurred before React could mount.</pre>'
  }
}

mount()
