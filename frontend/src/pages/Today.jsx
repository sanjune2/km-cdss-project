
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import './Today.css'


const initialPatients = [
  {
    id: 1,
    name: '김민수',
    birthDate: '1990-03-15',
    phone: '010-1234-5678',
    address: '서울특별시 강남구',
    guardianName: '',
    guardianRelation: '',
    guardianPhone: '',
    time: '09:10',
    status: '대기',
    doctor: null,
  },
  {
    id: 2,
    name: '이서연',
    birthDate: '1985-07-22',
    phone: '010-2345-6789',
    address: '서울특별시 송파구',
    guardianName: '',
    guardianRelation: '',
    guardianPhone: '',
    time: '09:25',
    status: '대기',
    doctor: null,
  },
  {
    id: 3,
    name: '박지훈',
    birthDate: '1978-11-08',
    phone: '010-3456-7890',
    address: '서울특별시 마포구',
    guardianName: '',
    guardianRelation: '',
    guardianPhone: '',
    time: '09:40',
    status: '진료 중',
    doctor: '담당 한의사',
  },
  {
    id: 4,
    name: '최유진',
    birthDate: '1995-05-19',
    phone: '010-4567-8901',
    address: '서울특별시 서초구',
    guardianName: '',
    guardianRelation: '',
    guardianPhone: '',
    time: '10:00',
    status: '완료',
    doctor: null,
  },
]


export default function Today() {
  const navigate = useNavigate()
  const [patients, setPatients] = useState([])
  const [role, setRole] = useState('한의사')

  useEffect(() => {
    const loadWaitingPatients = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/api/waiting', {
          credentials: 'include',
        })

        if (!response.ok) {
          throw new Error('대기 목록 조회 실패')
        }

        const data = await response.json()

        setPatients(
          data.patients.map((patient) => ({
            ...patient,
            time: patient.time || '-',
            status: patient.status || '대기',
            doctor: patient.doctor || null,
          }))
        )
      } catch (error) {
        console.error('대기 목록 불러오기 오류:', error)
      }
    }

    loadWaitingPatients()
  }, [])


  const waiting = patients.filter((p) => p.status === '대기').length
  const consulting = patients.filter((p) => p.status === '진료 중').length
  const completed = patients.filter((p) => p.status === '완료').length


  const startConsultation = async (id) => {
    try {
      const response = await fetch(
        `http://127.0.0.1:8000/api/waiting/${id}`,
        {
          method: 'PATCH',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            status: '진료 중',
            doctor: '담당 한의사',
          }),
        }
      )

      const data = await response.json()

      if (!response.ok) {
        alert(data.detail || '상담 시작에 실패했습니다.')
        return
      }

    setPatients((prev) =>
      prev.map((p) =>
        p.id === id ? { ...p, ...data.patient } : p
      )
    )
  } catch (error) {
    console.error('상담 시작 오류:', error)
    alert('서버 연결에 실패했습니다.')
  }
}

  const cancelConsultation = async (id) => {
    if (!window.confirm('상담을 취소하시겠습니까?')) return

    try {
      const response = await fetch(`http://127.0.0.1:8000/api/waiting/${id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          status: '대기',
          doctor: null,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        alert(data.detail || '상담 취소에 실패했습니다.')
        return
      }

      setPatients((prev) =>
        prev.map((p) =>
          p.id === id ? { ...p, ...data.patient } : p
        )
      )
    } catch (error) {
      console.error('상담 취소 오류:', error)
      alert('서버 연결에 실패했습니다.')
    }
  }

  const cancelReception = async (id) => {
    if (!window.confirm('접수를 취소하시겠습니까?')) return

    try {
      const response = await fetch(`http://127.0.0.1:8000/api/waiting/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })

      const data = await response.json()

      if (!response.ok) {
        alert(data.detail || '접수 취소에 실패했습니다.')
        return
      }

      setPatients((prev) =>
        prev.filter((p) => p.id !== id)
      )

      alert('접수가 취소되었습니다.')
    } catch (error) {
      console.error('접수 취소 오류:', error)
      alert('서버 연결에 실패했습니다.')
    }
  }


  return (
    <div className="today-page">
      <div className="today-heading">
        <h2>오늘의 업무</h2>

        <label>
          테스트 직무:{' '}
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="원장">원장</option>
            <option value="한의사">한의사</option>
            <option value="안내데스크">안내데스크</option>
          </select>
        </label>
      </div>

      <div className="today-summary">
        <div className="summary-card">
          <span>전체 접수</span>
          <strong>{patients.length}명</strong>
        </div>
        <div className="summary-card">
          <span>상담 대기</span>
          <strong>{waiting}명</strong>
        </div>
        <div className="summary-card">
          <span>진료 중</span>
          <strong>{consulting}명</strong>
        </div>
        <div className="summary-card">
          <span>완료</span>
          <strong>{completed}명</strong>
        </div>
      </div>

      <section className="today-section">
        <h3>상담 대기·진행 환자 목록</h3>

        <table className="patient-table">
          <thead>
            <tr>
              <th>접수 시간</th>
              <th>환자명</th>
              <th>상태</th>
              <th>담당자</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {patients
              .filter((patient) => patient.status !== '완료')
              .map((patient) => (
              <tr key={patient.id}>
                <td>{patient.time}</td>
                <td>{patient.name}</td>
                <td>
                  <span className={
                    patient.status === '대기'
                      ? 'status waiting'
                      : patient.status === '진료 중'
                        ? 'status consulting'
                        : 'status completed'
                  }>
                    {patient.status}
                  </span>
                </td>
                <td>{patient.doctor || '-'}</td>
                <td>
                  <div className="patient-actions">
                    {patient.status === '대기' && role !== '안내데스크' && (
                      <button onClick={() => startConsultation(patient.id)}>
                        상담 시작
                      </button>
                    )}

                    {patient.status === '대기' && role === '안내데스크' && (
                      <button
                        className="danger-button"
                        onClick={() => cancelReception(patient.id)}
                      >
                        접수 취소
                      </button>
                    )}

                    {patient.status === '진료 중' &&
                      role !== '안내데스크' && (
                        <>

                          <button
                            onClick={() =>
                              navigate('/consultation', {
                                state: {
                                  patient: { ...patient },
                                  source: 'today',
                                },
                              })
                            }
                          >
                            일지 작성
                          </button>

                          <button
                            className="danger-button"
                            onClick={() => cancelConsultation(patient.id)}
                          >
                            상담 취소
                          </button>
                        </>
                      )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

<section className="today-section">
  <h3>빠른 메뉴</h3>

  <div className="today-quick-menu">
    <div className="quick-menu-card">
      <h4>내 프로필</h4>
      <p>내 계정 정보를 확인합니다.</p>
      <button onClick={() => navigate('/account')}>
        프로필 보기
      </button>
    </div>

    <div className="quick-menu-card">
      <h4>조회 날짜</h4>
      <p>과거 상담 기록을 조회합니다.</p>
      <input
        type="date"
        onChange={(e) => {
          if (e.target.value) {
            navigate('/patients', {
              state: {
                view: 'history',
                date: e.target.value,
              },
            })
          }
        }}
      />
    </div>

    <div className="quick-menu-card">
      <h4>업무 채팅</h4>
      <p>직원 간 채팅방을 확인합니다.</p>
      <button
        onClick={() =>
          navigate('/account', {
            state: { view: 'chat' },
          })
        }
      >
        채팅방 보기
      </button>
    </div>
  </div>
</section>

      <section className="today-section">
        <h3>이어서 처리할 업무</h3>
        <p>저장된 처방전 및 전송 대기 업무가 표시될 영역입니다.</p>
        <button onClick={() => navigate('/prescriptions')}>
          처방전 보기
        </button>
      </section>
    </div>
  )
}
