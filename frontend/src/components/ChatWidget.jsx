import { useEffect, useRef, useState } from 'react'

export default function ChatWidget({ onClose }) {
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [myAccountId, setMyAccountId] = useState(null)
  const messageContainerRef = useRef(null)
  const shouldAutoScrollRef = useRef(true)
  const hasInitialScrolledRef = useRef(false)

  useEffect(() => {
      const loadMyAccount = async () => {
        try {
          const response = await fetch('/api/auth/me', {
            credentials: 'include',
          })

          if (!response.ok) {
            throw new Error('로그인 정보를 확인할 수 없습니다.')
          }

          const data = await response.json()
          setMyAccountId(data.id)
        } catch (err) {
          setError(err.message)
        }
      }

      loadMyAccount()
    }, [])

  // 기존 채팅 메시지 조회
  useEffect(() => {
      let isActive = true
      let isFetching = false

      const loadMessages = async () => {
        if (isFetching) return

        isFetching = true

        try {
          const response = await fetch('/api/chat/messages', {
            credentials: 'include',
          })

          if (response.status === 401) {
              const authError = new Error('로그인이 필요합니다.')
              authError.status = 401
              throw authError
            }

            if (!response.ok) {
              throw new Error('채팅 메시지를 불러오지 못했습니다.')
            }

          const data = await response.json()

          if (isActive) {
            setMessages(data.messages || [])
            setError('')
          }
        } catch (err) {
          if (isActive) {
            setError(err.message)

            if (err.status === 401) {
              setMessages([])
            }
          }
        } finally {
          isFetching = false

          if (isActive) {
            setLoading(false)
          }
        }
      }

      loadMessages()

      const intervalId = setInterval(loadMessages, 3000)

      return () => {
        isActive = false
        clearInterval(intervalId)
      }
    }, [])
    const handleMessageScroll = () => {
      const container = messageContainerRef.current
      if (!container) return

      const distanceFromBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight

      shouldAutoScrollRef.current = distanceFromBottom <= 80
    }

    useEffect(() => {
      const container = messageContainerRef.current

      if (!container || loading) return

      if (!hasInitialScrolledRef.current || shouldAutoScrollRef.current) {
        container.scrollTop = container.scrollHeight
        hasInitialScrolledRef.current = true
      }
    }, [messages, loading])
    const sendMessage = async () => {
  const text = message.trim()

  if (!text || sending) return

  if (text.length > 2000) {
    alert('메시지는 2000자 이하로 입력해 주세요.')
    return
  }

  setSending(true)

  try {
    const response = await fetch('/api/chat/messages', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message: text }),
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || '메시지 전송에 실패했습니다.')
    }

    setMessages((prev) => [...prev, data.chatMessage])
    setMessage('')
  } catch (err) {
    alert(err.message)
      } finally {
        setSending(false)
      }
    }
      return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: '#ffffff',
        border: '1px solid #cccccc',
        borderRadius: '12px',
        boxShadow: '0 8px 30px rgba(0, 0, 0, 0.2)',
        zIndex: 9999,
        overflow: 'hidden',
      }}
    >

      {/* 드래그 가능한 제목 표시줄 */}
      <div
        style={{
          backgroundColor: '#267a62',
          color: 'white',
          padding: '12px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          userSelect: 'none',
        }}
      >
        <strong>직원 채팅방</strong>

        <button
          onClick={onClose}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'white',
            fontSize: '20px',
            cursor: 'pointer',
          }}
        >
          ×
        </button>
      </div>

      {/* 메시지 표시 영역 */}
      <div
          ref={messageContainerRef}
          onScroll={handleMessageScroll}
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            padding: '12px',
            backgroundColor: '#f7f9f8',
          }}
        >
        {loading && <p>메시지를 불러오는 중...</p>}

        {error && <p style={{ color: 'red' }}>{error}</p>}

        {!loading && !error && messages.length === 0 && (
          <p style={{ color: '#888', textAlign: 'center' }}>
            아직 메시지가 없습니다.
          </p>
        )}

        {messages.map((item) => {
          const isMine = Number(item.senderId) === Number(myAccountId)

          return (
              <div
                key={item.id}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: isMine ? 'flex-end' : 'flex-start',
                  marginBottom: '14px',
                }}
              >
                <small
                  style={{
                    marginBottom: '5px',
                    color: '#777',
                    fontSize: '11px',
                  }}
                >
                  {isMine ? '나' : `${item.senderName} (${item.senderRole})`}
                </small>

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-end',
                    flexDirection: isMine ? 'row-reverse' : 'row',
                    gap: '6px',
                    maxWidth: '90%',
                  }}
                >
                  <div
                    style={{
                      padding: '10px 12px',
                      backgroundColor: isMine ? '#d5eee2' : '#ffffff',
                      borderRadius: isMine
                        ? '12px 4px 12px 12px'
                        : '4px 12px 12px 12px',
                      fontSize: '13px',
                      lineHeight: '1.5',
                      color: '#222',
                      wordBreak: 'break-word',
                      overflowWrap: 'anywhere',
                      whiteSpace: 'pre-wrap',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                    }}
                  >
                    {item.message}
                  </div>

                  <span
                    style={{
                      fontSize: '10px',
                      color: '#999',
                      whiteSpace: 'nowrap',
                      flexShrink: 0,
                    }}
                  >
                    {item.sentAt
                      ? new Date(item.sentAt).toLocaleTimeString('ko-KR', {
                          hour: 'numeric',
                          minute: '2-digit',
                        })
                      : ''}
                  </span>
                </div>
              </div>
            )
            })}
      </div>

      {/* 메시지 입력 영역 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '10px',
            borderTop: '1px solid #e5e5e5',
            backgroundColor: '#ffffff',
            gap: '8px',
          }}
        >
          <input
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.nativeEvent.isComposing &&
                !sending
              ) {
                event.preventDefault()
                sendMessage()
              }
            }}
            placeholder="메시지를 입력하세요."
            maxLength={2000}
            style={{
              flex: 1,
              minWidth: 0,
              padding: '11px 12px',
              border: '1px solid #dddddd',
              borderRadius: '8px',
              outlineColor: '#267a62',
              fontSize: '13px',
              backgroundColor: '#f8faf9',
              boxSizing: 'border-box',
            }}
          />

          <button
            onClick={sendMessage}
            disabled={sending || !message.trim()}
            style={{
              padding: '11px 15px',
              border: 'none',
              borderRadius: '8px',
              backgroundColor:
                sending || !message.trim() ? '#d5ddd9' : '#267a62',
              color:
                sending || !message.trim() ? '#888888' : '#ffffff',
              fontSize: '13px',
              fontWeight: 'bold',
              cursor:
                sending || !message.trim() ? 'not-allowed' : 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            {sending ? '전송 중' : '전송'}
          </button>
        </div>
    </div>
  )
}