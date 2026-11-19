
import { useCallback, useEffect, useState } from 'react'

const roleLabels = {
  DOCTOR: '한의사',
  DESK: '안내데스크',
}

const statusLabels = {
  ACTIVE: '활성',
  PENDING: '승인대기',
  SUSPENDED: '이용중지',
  DELETED: '삭제',
  EXPIRED: '만료',
}

export default function Staff() {
  const [staff, setStaff] = useState([])
  const [invitations, setInvitations] = useState([])
  const [filter, setFilter] = useState('ALL')
  const [email, setEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('DOCTOR')
  const [inviteToken, setInviteToken] = useState('')
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')

  const request = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: 'include',
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })

    const data = await response.json().catch(() => ({}))

    if (!response.ok) {
      throw new Error(
        typeof data.detail === 'string'
          ? data.detail
          : '요청 처리에 실패했습니다.'
      )
    }

    return data
  }

  const loadStaff = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const data = await request('/api/staff')
      setStaff(data.staff || [])
      setInvitations(data.invitations || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStaff()
  }, [loadStaff])

  const inviteStaff = async (event) => {
    event.preventDefault()

    if (!email.trim()) {
      alert('이메일을 입력해 주세요.')
      return
    }

    setWorking(true)

    try {
      const data = await request('/api/staff/invitations', {
        method: 'POST',
        body: JSON.stringify({
          email: email.trim(),
          role: inviteRole,
        }),
      })

      setInviteToken(data.token)
      setEmail('')
      await loadStaff()
      alert('초대 링크가 생성되었습니다.')
    } catch (err) {
      alert(err.message)
    } finally {
      setWorking(false)
    }
  }

  const changeStaff = async (id, action, body, message) => {
    if (!window.confirm(`${message} 진행할까요?`)) return

    setWorking(true)

    try {
      await request(`/api/staff/${id}/${action}`, {
        method: 'PATCH',
        ...(body ? { body: JSON.stringify(body) } : {}),
      })

      await loadStaff()
      alert(`${message} 완료되었습니다.`)
    } catch (err) {
      alert(err.message)
    } finally {
      setWorking(false)
    }
  }

  const deleteStaff = async (id) => {
    if (!window.confirm('직원을 삭제 처리할까요?')) return

    setWorking(true)

    try {
      await request(`/api/staff/${id}`, {
        method: 'DELETE',
      })

      await loadStaff()
      alert('직원이 삭제 처리되었습니다.')
    } catch (err) {
      alert(err.message)
    } finally {
      setWorking(false)
    }
  }

  const changeRole = async (person) => {
    const nextRole = person.role === 'DOCTOR' ? 'DESK' : 'DOCTOR'

    await changeStaff(
      person.id,
      'role',
      { role: nextRole },
      `직무를 ${roleLabels[nextRole]}(으)로 변경`
    )
  }

  const visibleStaff = staff.filter((person) => {
    if (filter === 'ALL') return true
    return person.status === filter
  })

  const visibleInvitations =
    filter === 'ALL' || filter === 'INVITED'
      ? invitations
      : []

  const invitationLink = inviteToken
    ? `${window.location.origin}/staff/register?token=${encodeURIComponent(inviteToken)}`
    : ''

  const copyInvitationLink = async () => {
    try {
      await navigator.clipboard.writeText(invitationLink)
      alert('초대 링크가 복사되었습니다.')
    } catch {
      window.prompt('초대 링크를 복사해 주세요.', invitationLink)
    }
  }

  const cellStyle = {
    padding: '12px',
    borderBottom: '1px solid #ddd',
    textAlign: 'left',
    whiteSpace: 'nowrap',
  }

  const buttonStyle = {
    padding: '7px 10px',
    margin: '3px',
    cursor: 'pointer',
  }

  return (
    <div style={{ padding: '24px' }}>
      <h2>직원 관리</h2>

      <section style={{
        padding: '20px',
        border: '1px solid #ddd',
        borderRadius: '8px',
        marginBottom: '24px',
      }}>
        <h3>직원 초대</h3>

        <form onSubmit={inviteStaff}>
          <div style={{
            display: 'flex',
            gap: '10px',
            flexWrap: 'wrap',
          }}>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="직원 이메일"
              required
              style={{ padding: '9px', minWidth: '240px' }}
            />

            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              style={{ padding: '9px' }}
            >
              <option value="DOCTOR">한의사</option>
              <option value="DESK">안내데스크</option>
            </select>

            <button type="submit" disabled={working}>
              직원 초대
            </button>
          </div>
        </form>

        {invitationLink && (
          <div style={{
            marginTop: '16px',
            padding: '12px',
            backgroundColor: '#f4f4f4',
            borderRadius: '6px',
          }}>
            <strong>초대 링크</strong>
            <p style={{ overflowWrap: 'anywhere' }}>
              {invitationLink}
            </p>
            <button onClick={copyInvitationLink}>
              링크 복사
            </button>
            <p style={{ fontSize: '13px', color: '#666' }}>
              실제 이메일 발송은 아직 연결되지 않았습니다.
            </p>
          </div>
        )}
      </section>

      <section>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <h3>직원 목록</h3>
          <button onClick={loadStaff}>새로고침</button>
        </div>

        <div style={{
          display: 'flex',
          gap: '8px',
          flexWrap: 'wrap',
        }}>
          {[
            ['ALL', '전체'],
            ['INVITED', '초대대기'],
            ['PENDING', '승인대기'],
            ['ACTIVE', '활성'],
            ['SUSPENDED', '이용중지'],
          ].map(([value, label]) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              style={{
                padding: '8px 14px',
                backgroundColor:
                  filter === value ? '#dcefe2' : 'white',
                border: '1px solid #ccc',
                borderRadius: '5px',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {error && (
          <p style={{ color: 'red' }}>{error}</p>
        )}

        {loading ? (
          <p>직원 목록을 불러오는 중입니다...</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{
              width: '100%',
              borderCollapse: 'collapse',
              marginTop: '16px',
            }}>
              <thead>
                <tr>
                  {['직원명', '이메일', '직책', '권한', '상태', '작업'].map(
                    (heading) => (
                      <th key={heading} style={cellStyle}>
                        {heading}
                      </th>
                    )
                  )}
                </tr>
              </thead>

              <tbody>
                {visibleStaff.map((person) => (
                  <tr key={person.id}>
                    <td style={cellStyle}>
                      {person.name || '-'}
                    </td>
                    <td style={cellStyle}>{person.email}</td>
                    <td style={cellStyle}>
                      {person.isOwner
                        ? '원장'
                        : roleLabels[person.role]}
                    </td>
                    <td style={cellStyle}>
                      {person.isOwner
                        ? '전체 관리'
                        : person.role === 'DOCTOR'
                          ? '진료·처방'
                          : '접수·수납'}
                    </td>
                    <td style={cellStyle}>
                      {statusLabels[person.status] || person.status}
                    </td>
                    <td style={cellStyle}>
                      {!person.isOwner && (
                        <>
                          {person.status === 'PENDING' && (
                            <button
                              style={buttonStyle}
                              disabled={working}
                              onClick={() => changeStaff(
                                person.id,
                                'approve',
                                null,
                                '직원 승인'
                              )}
                            >
                              승인
                            </button>
                          )}

                          <button
                            style={buttonStyle}
                            disabled={working}
                            onClick={() => changeRole(person)}
                          >
                            직무 변경
                          </button>

                          {person.status === 'ACTIVE' && (
                            <button
                              style={buttonStyle}
                              disabled={working}
                              onClick={() => changeStaff(
                                person.id,
                                'suspend',
                                null,
                                '직원 이용중지'
                              )}
                            >
                              이용중지
                            </button>
                          )}
                            {person.status === 'SUSPENDED' && (
                              <button
                                style={buttonStyle}
                                disabled={working}
                                onClick={() => changeStaff(
                                  person.id,
                                  'resume',
                                  null,
                                  '직원 이용재개'
                                )}
                              >
                                이용재개
                              </button>
                            )}


                          <button
                            style={buttonStyle}
                            disabled={working}
                            onClick={() => deleteStaff(person.id)}
                          >
                            삭제
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}

                {visibleInvitations.map((invitation) => (
                  <tr key={`invite-${invitation.id}`}>
                    <td style={cellStyle}>-</td>
                    <td style={cellStyle}>{invitation.email}</td>
                    <td style={cellStyle}>
                      {roleLabels[invitation.role]}
                    </td>
                    <td style={cellStyle}>
                      {invitation.role === 'DOCTOR'
                        ? '진료·처방'
                        : '접수·수납'}
                    </td>
                    <td style={cellStyle}>
                      {statusLabels[invitation.status] || '초대대기'}
                    </td>
                    <td style={cellStyle}>-</td>
                  </tr>
                ))}

                {visibleStaff.length === 0 &&
                  visibleInvitations.length === 0 && (
                    <tr>
                      <td
                        colSpan={6}
                        style={{
                          ...cellStyle,
                          textAlign: 'center',
                        }}
                      >
                        표시할 직원이 없습니다.
                      </td>
                    </tr>
                  )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
