
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

const roleLabels = {
  DOCTOR: '한의사',
  DESK: '안내데스크',
}

export default function StaffRegister() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  const [email, setEmail] = useState('')
  const [role, setRole] = useState('')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')

  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    const verifyInvitation = async () => {
      if (!token) {
        setError('초대 링크에 토큰이 없습니다.')
        setLoading(false)
        return
      }

      try {
        const response = await fetch(
          `/api/staff/invitations/verify?token=${encodeURIComponent(token)}`,
          { credentials: 'include' }
        )

        const data = await response.json()

        if (!response.ok) {
          throw new Error(
            typeof data.detail === 'string'
              ? data.detail
              : '유효하지 않거나 만료된 초대입니다.'
          )
        }

        setEmail(data.email)
        setRole(data.role)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }

    verifyInvitation()
  }, [token])

  const handleSubmit = async (event) => {
    event.preventDefault()

    if (!name.trim()) {
      alert('이름을 입력해 주세요.')
      return
    }

    if (password.length < 8 || password.length > 128) {
      alert('비밀번호는 8~128자로 입력해 주세요.')
      return
    }

    if (password !== passwordConfirm) {
      alert('비밀번호가 일치하지 않습니다.')
      return
    }

    setSubmitting(true)
    setError('')

    try {
      const response = await fetch('/api/staff/register', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          token,
          name: name.trim(),
          password,
          phone: phone.trim() || null,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : '직원 가입에 실패했습니다.'
        )
      }

      setSuccess(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div style={{ padding: '40px' }}>초대 정보를 확인하고 있습니다...</div>
  }

  if (success) {
    return (
      <div style={styles.container}>
        <div style={styles.card}>
          <h2>가입이 완료되었습니다.</h2>
          <p>{email}</p>
          <p>가입 신청이 완료되었습니다.</p>
          <p>원장의 승인을 기다려 주세요.</p>
        </div>
      </div>
    )
  }

  if (error && !email) {
    return (
      <div style={styles.container}>
        <div style={styles.card}>
          <h2>직원 가입</h2>
          <p style={styles.error}>{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h2>한의결 직원 가입</h2>
        <p style={styles.description}>
          초대받은 직원 정보를 입력해 주세요.
        </p>

        {error && <p style={styles.error}>{error}</p>}

        <form onSubmit={handleSubmit}>
          <label style={styles.label}>이메일</label>
          <input
            value={email}
            readOnly
            style={styles.input}
          />

          <label style={styles.label}>직책</label>
          <input
            value={roleLabels[role] || role}
            readOnly
            style={styles.input}
          />

          <label style={styles.label}>직원 이름</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="이름을 입력해 주세요."
            maxLength={100}
            required
            style={styles.input}
          />

          <label style={styles.label}>전화번호 (선택)</label>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="전화번호를 입력해 주세요."
            style={styles.input}
          />

          <label style={styles.label}>비밀번호</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="8~128자"
            minLength={8}
            maxLength={128}
            required
            style={styles.input}
          />

          <label style={styles.label}>비밀번호 확인</label>
          <input
            type="password"
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
            placeholder="비밀번호를 다시 입력해 주세요."
            required
            style={styles.input}
          />

          <button
            type="submit"
            disabled={submitting}
            style={styles.button}
          >
            {submitting ? '가입 처리 중...' : '가입하기'}
          </button>
        </form>
      </div>
    </div>
  )
}

const styles = {
  container: {
    minHeight: '80vh',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    padding: '30px',
  },
  card: {
    width: '440px',
    maxWidth: '100%',
    padding: '30px',
    backgroundColor: 'white',
    borderRadius: '10px',
    boxShadow: '0 2px 12px rgba(0,0,0,0.1)',
  },
  description: {
    color: '#666',
    marginBottom: '24px',
  },
  label: {
    display: 'block',
    fontWeight: 'bold',
    marginTop: '16px',
    marginBottom: '7px',
  },
  input: {
    width: '100%',
    boxSizing: 'border-box',
    padding: '11px',
    border: '1px solid #ccc',
    borderRadius: '5px',
  },
  button: {
    width: '100%',
    padding: '13px',
    marginTop: '24px',
    backgroundColor: '#245f4b',
    color: 'white',
    border: 'none',
    borderRadius: '5px',
    cursor: 'pointer',
  },
  error: {
    color: 'red',
    marginTop: '12px',
  },
}
