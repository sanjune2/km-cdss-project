import ChatWidget from '../components/ChatWidget'

export default function ChatPopup() {
  return (
    <div
      style={{
        width: '100%',
        height: '100vh',
        margin: 0,
        padding: 0,
        overflow: 'hidden',
        backgroundColor: '#f7f9f8',
      }}
    >
      <ChatWidget onClose={() => window.close()} />
    </div>
  )
}