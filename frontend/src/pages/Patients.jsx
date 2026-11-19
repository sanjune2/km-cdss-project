
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
const testPatients = [
  {
    id: 1,
    name: '김민수',
    birthDate: '1990-03-15',
    phone: '010-1234-5678',
    address: '서울특별시 마포구',
  },
  {
    id: 2,
    name: '이서연',
    birthDate: '1985-07-22',
    phone: '010-2345-6789',
    address: '서울특별시 강남구',
  },
  {
    id: 3,
    name: '박지훈',
    birthDate: '1978-11-08',
    phone: '010-3456-7890',
    address: '경기도 고양시',
  },
]

export default function Patients({ currentRole }) {
  const location = useLocation()
  const [selectedMenu, setSelectedMenu] = useState(
    location.state?.view === 'history' ? 'history' : 'search'
  )
  const [searchKeyword, setSearchKeyword] = useState('')
  const [patients, setPatients] = useState([])
  const [editPatient, setEditPatient] = useState(null)
  const [detailPatient, setDetailPatient] = useState(null)

useEffect(() => {
  const loadPatients = async () => {
    try {
      const response = await fetch('/api/patients', {
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error('환자 목록 조회 실패')
      }

      const data = await response.json()
      setPatients(data.patients || [])
    } catch (error) {
      console.error('환자 목록 조회 오류:', error)
    }
  }

  loadPatients()
}, [])


  const [consultationRecords, setConsultationRecords] = useState([])
  const [prescriptionRecords, setPrescriptionRecords] = useState([])
  const [historyDate, setHistoryDate] = useState(
    location.state?.date || new Date().toLocaleDateString('en-CA')
  )
  const [selectedRecord, setSelectedRecord] = useState(null)
  const [selectedPrescription, setSelectedPrescription] = useState(null)
  const [historyError, setHistoryError] = useState('')
  const [detailTab, setDetailTab] = useState('consultation')


  const registerWaitingPatient = async () => {
    if (!detailPatient) return

    try {
      const response = await fetch('/api/waiting', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          id: detailPatient.id,
          name: detailPatient.name,
          birthDate: detailPatient.birthDate,
          phone: detailPatient.phone,
          address: detailPatient.address,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        alert(data.detail || '상담 대기 등록에 실패했습니다.')
        return
      }

      alert('상담 대기 등록이 완료되었습니다.')
      setDetailPatient(null)
    } catch (error) {
      console.error('상담 대기 등록 오류:', error)
      alert('서버 연결에 실패했습니다.')
    }
  }

  const [patientForm, setPatientForm] = useState({
  name: '',
  birthDate: '',
  phone: '',
  address: '',
  guardianName: '',
  guardianRelation: '',
  guardianPhone: '',
})
const handleEditChange = (e) => {
  const { name, value } = e.target

  setEditPatient((prev) => ({
    ...prev,
    [name]: value,
  }))
}


const saveEditedPatient = async () => {
  if (!editPatient.name.trim()) {
    alert('성명을 입력해 주세요.')
    return
  }

  if (!editPatient.birthDate) {
    alert('생년월일을 입력해 주세요.')
    return
  }

  if (!editPatient.phone.trim()) {
    alert('연락처를 입력해 주세요.')
    return
  }

  if (!editPatient.address.trim()) {
    alert('주소를 입력해 주세요.')
    return
  }

  try {
    const response = await fetch(
      `/api/patients/${editPatient.id}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: editPatient.name,
          birthDate: editPatient.birthDate,
          phone: editPatient.phone,
          address: editPatient.address,
          guardianName: editPatient.guardianName || '',
          guardianRelation: editPatient.guardianRelation || '',
          guardianPhone: editPatient.guardianPhone || '',
        }),
      }
    )

    const data = await response.json()

    if (!response.ok) {
      alert(data.detail || '환자 정보 수정에 실패했습니다.')
      return
    }

    setPatients((prev) =>
      prev.map((patient) =>
        patient.id === editPatient.id ? data.patient : patient
      )
    )

    setEditPatient(null)
    alert('환자 정보가 수정되었습니다.')
  } catch (error) {
    console.error('환자 정보 수정 오류:', error)
    alert('서버 연결에 실패했습니다.')
  }
}

const handleInputChange = (e) => {
  const { name, value } = e.target

  setPatientForm((prev) => ({
    ...prev,
    [name]: value,
  }))
}

const validatePatient = async (registerWaiting = false) => {
  if (!patientForm.name.trim()) {
    alert('성명을 입력해 주세요.')
    return
  }

  if (!patientForm.birthDate) {
    alert('생년월일을 입력해 주세요.')
    return
  }

  if (!patientForm.phone.trim()) {
    alert('연락처를 입력해 주세요.')
    return
  }

  if (!patientForm.address.trim()) {
    alert('주소를 입력해 주세요.')
    return
  }

  try {
    const response = await fetch('/api/patients', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(patientForm),
    })

    const data = await response.json()

    if (!response.ok) {
      alert(data.detail || '환자 등록에 실패했습니다.')
      return
    }

    setPatients((prev) => [...prev, data.patient])

    if (registerWaiting) {
      const waitingResponse = await fetch('/api/waiting', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          id: data.patient.id,
          name: data.patient.name,
          birthDate: data.patient.birthDate,
          phone: data.patient.phone,
          address: data.patient.address,
        }),
      })

      if (!waitingResponse.ok) {
        const waitingData = await waitingResponse.json()
        alert(
          `환자 정보는 저장됐지만 상담대기등록에 실패했습니다.\n${waitingData.detail || ''}`
        )
        setSelectedMenu('search')
        return
      }
    }


    setPatientForm({
      name: '',
      birthDate: '',
      phone: '',
      address: '',
      guardianName: '',
      guardianRelation: '',
      guardianPhone: '',
    })

    alert(registerWaiting ? '환자 등록 및 상담대기등록이 완료되었습니다.' : '환자 등록이 완료되었습니다.')
    setSelectedMenu('search')
  } catch (error) {
    console.error('환자 등록 오류:', error)
    alert('서버 연결에 실패했습니다.')
  }
}


  useEffect(() => {
    if (selectedMenu !== 'history') return
    const loadPrescriptionRecords = async () => {
      try {
        const response = await fetch(
          '/api/prescriptions',
          {
            credentials: 'include',
          }
        )

        if (!response.ok) {
          throw new Error('처방전 조회에 실패했습니다.')
        }

        const data = await response.json()
        setPrescriptionRecords(data.records || [])
      } catch (error) {
        console.error('처방전 조회 오류:', error)
        setHistoryError('처방전 기록을 불러오지 못했습니다.')
      }
      }

      const loadConsultationRecords = async () => {
        try {
          setHistoryError('')

        const response = await fetch(
          '/api/consultations',
          {
            credentials: 'include',
          }
        )

        if (!response.ok) {
          throw new Error('상담 기록 조회에 실패했습니다.')
        }

        const data = await response.json()
        setConsultationRecords(data.records || [])
      } catch (error) {
        console.error('상담 기록 조회 오류:', error)
        setHistoryError('상담 기록을 불러오지 못했습니다.')
      }
    }
      loadPrescriptionRecords()

      if (currentRole !== 'desk') {
        loadConsultationRecords()
      }
    }, [selectedMenu, currentRole])

  const filteredConsultations = consultationRecords.filter(
    (record) => record.createdAt?.slice(0, 10) === historyDate
  )

  const filteredPrescriptions = prescriptionRecords.filter(
    (record) => record.createdAt?.slice(0, 10) === historyDate
  )

  return (
    <div>
      <h2>환자 관리</h2>

      {!selectedMenu && (
        <div>
          <button
            type="button"
            onClick={() => setSelectedMenu('search')}
          >
            환자 검색 및 정보 조회·수정
          </button>

          <button
            type="button"
            onClick={() => setSelectedMenu('register')}
          >
            신규 환자 등록
          </button>

          <button
            type="button"
            onClick={() => setSelectedMenu('history')}
          >
            {currentRole === 'desk' ? '과거 처방전 기록확인' : '과거상담 기록확인'}
          </button>
        </div>
      )}

      {selectedMenu && (
        <div>
          <button
            type="button"
            onClick={() => setSelectedMenu(null)}
          >
            환자 관리로 돌아가기
          </button>

          {selectedMenu === 'search' && (
            <div>
              <h3>환자 검색 및 정보 조회·수정</h3>

              <div style={{ marginBottom: '20px' }}>
                <input
                  type="text"
                  value={searchKeyword}
                  onChange={(e) => setSearchKeyword(e.target.value)}
                  placeholder="환자 이름을 입력해 주세요."
                  style={{
                    width: '300px',
                    padding: '10px',
                    marginRight: '8px',
                  }}
                />
              </div>

              <table
                style={{
                  borderCollapse: 'collapse',
                  width: '100%',
                  maxWidth: '900px',
                }}
              >
                <thead>
                  <tr>
                    <th>성명</th>
                    <th>생년월일</th>
                    <th>연락처</th>
                    <th>주소</th>
                    <th>작업</th>
                  </tr>
                </thead>

                <tbody>
                  {patients
                    .filter((patient) =>
                      patient.name.includes(searchKeyword.trim())
                    )
                    .map((patient) => (
                      <tr key={patient.id}>
                        <td>{patient.name}</td>
                        <td>{patient.birthDate}</td>
                        <td>{patient.phone}</td>
                        <td>{patient.address}</td>
                        <td>
                          <button
                            type="button"
                            onClick={() => setDetailPatient(patient)}
                          >
                            상세보기
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditPatient({ ...patient })}
                          >
                            수정
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}

          {selectedMenu === 'register' && (
            <div>
              <h3>신규 환자 등록</h3>

              <div style={{ display: 'grid', gap: '12px', maxWidth: '500px' }}>
              <label>
                성명 (필수)
                <input
                  type="text"
                  name="name"
                  value={patientForm.name}
                  onChange={handleInputChange}
                  placeholder="환자 성명"
                />
              </label>

              <label>
                생년월일 (필수)
                <input
                  type="date"
                  name="birthDate"
                  value={patientForm.birthDate}
                  onChange={handleInputChange}
                />
              </label>

              <label>
                연락처 (필수)
                <input
                  type="tel"
                  name="phone"
                  value={patientForm.phone}
                  onChange={handleInputChange}
                  placeholder="010-0000-0000"
                />
              </label>

              <label>
                주소 (필수)
                <input
                  type="text"
                  name="address"
                  value={patientForm.address}
                  onChange={handleInputChange}
                  placeholder="주소 입력"
                />
              </label>

              <h4>보호자 정보 (선택)</h4>

              <label>
                보호자 이름
                <input
                  type="text"
                  name="guardianName"
                  value={patientForm.guardianName}
                  onChange={handleInputChange}
                  placeholder="보호자 이름"
                />
              </label>

              <label>
                관계
                <input
                  type="text"
                  name="guardianRelation"
                  value={patientForm.guardianRelation}
                  onChange={handleInputChange}
                  placeholder="환자와의 관계"
                />
              </label>

              <label>
                보호자 연락처
                <input
                  type="tel"
                  name="guardianPhone"
                  value={patientForm.guardianPhone}
                  onChange={handleInputChange}
                  placeholder="010-0000-0000"
                />
              </label>
            </div>

              <div style={{ marginTop: '20px', display: 'flex', gap: '10px' }}>
                <button type="button" onClick={() => validatePatient(false)}>
                  저장
                </button>

                <button type="button" onClick={() => validatePatient(true)}>
                  저장 및 상담대기등록
                </button>
              </div>
            </div>
          )}


          {selectedMenu === 'history' && (
            <div>
              <h3>
                {currentRole === 'desk' ? '과거 처방전 기록확인' : '과거상담 기록확인'}
              </h3>

              <label>
                조회 날짜:{' '}
                <input
                  type="date"
                  value={historyDate}
                  onChange={(e) => setHistoryDate(e.target.value)}
                />
              </label>
              {currentRole === 'desk' && (
                <div style={{ marginTop: '20px' }}>
                  <h4>처방전 목록</h4>

                  <table style={{ width: '100%' }}>
                    <thead>
                      <tr>
                        <th>작성 날짜</th>
                        <th>환자명</th>
                        <th>처방명</th>
                        <th>상태</th>
                        <th>작업</th>
                      </tr>
                    </thead>

                    <tbody>
                      {filteredPrescriptions.map((record) => (
                        <tr key={record.id}>
                          <td>{record.createdAt?.slice(0, 10)}</td>
                          <td>{record.patientName}</td>
                          <td>{record.prescriptionName}</td>
                          <td>{record.status}</td>
                          <td>
                            <button
                              type="button"
                              onClick={() => setSelectedPrescription(record)}
                            >
                              상세보기
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {filteredPrescriptions.length === 0 && (
                    <p>선택한 날짜의 처방전이 없습니다.</p>
                  )}
                </div>
              )}

              {historyError && (
                <p style={{ color: 'red' }}>{historyError}</p>
              )}

              {currentRole !== 'desk' && (
              <table style={{ width: '100%', marginTop: '20px' }}>
                <thead>
                  <tr>
                    <th>상담 날짜</th>
                    <th>환자명</th>
                    <th>증상</th>
                    <th>작업</th>
                  </tr>
                </thead>

                <tbody>
                  {currentRole !== 'desk' && filteredConsultations.map((record) => (
                    <tr key={record.id}>
                      <td>{record.createdAt?.slice(0, 10)}</td>
                      <td>{record.patientName}</td>
                      <td>{record.symptoms}</td>
                      <td>
                        <button
                          type="button"
                          onClick={() => setSelectedRecord(record)}
                        >
                          상세보기
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
                  )}

              {currentRole !== 'desk' &&
                filteredConsultations.length === 0 &&
                !historyError && (
                  <p>선택한 날짜의 상담 기록이 없습니다.</p>
                )}

              {currentRole === 'desk' && selectedPrescription && (
                <div
                  style={{
                    position: 'fixed',
                    inset: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                  }}
                >
                  <div
                    role="dialog"
                    aria-modal="true"
                    aria-label="처방전 상세보기"
                    style={{
                      backgroundColor: 'white',
                      padding: '24px',
                      borderRadius: '10px',
                      width: '500px',
                      maxWidth: '90%',
                      maxHeight: '85vh',
                      overflowY: 'auto',
                    }}
                  >
                    <h3>처방전 상세보기</h3>

                    <p>환자명: {selectedPrescription.patientName}</p>
                    <p>처방명: {selectedPrescription.prescriptionName}</p>
                    <p>작성 날짜: {selectedPrescription.createdAt?.slice(0, 10)}</p>
                    <p>상태: {selectedPrescription.status}</p>

                    <h4>약재 구성</h4>

                    <table style={{ width: '100%' }}>
                      <thead>
                        <tr>
                          <th>약재명</th>
                          <th>용량(g)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(selectedPrescription.herbs || []).map((herb, index) => (
                          <tr key={index}>
                            <td>{herb.name}</td>
                            <td>{herb.amount}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    <button
                      type="button"
                      onClick={() => setSelectedPrescription(null)}
                      style={{ marginTop: '20px' }}
                    >
                      닫기
                    </button>
                  </div>
                </div>
              )}

              {selectedRecord && currentRole !== 'desk' && (
                <div
                  style={{
                    position: 'fixed',
                    inset: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                  }}
                >
                  <div
                    role="dialog"
                    aria-modal="true"
                    aria-label="상담일지 상세보기"
                    style={{
                      backgroundColor: 'white',
                      padding: '24px',
                      borderRadius: '10px',
                      width: '500px',
                      maxWidth: '90%',
                      maxHeight: '85vh',
                      overflowY: 'auto',
                    }}
                  >

                    <h3>상담 기록 상세보기</h3>

                    <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
                      <button
                        type="button"
                        onClick={() => setDetailTab('consultation')}
                        style={{
                          backgroundColor: detailTab === 'consultation' ? '#2563eb' : '#e5e7eb',
                          color: detailTab === 'consultation' ? 'white' : 'black',
                          padding: '10px 20px',
                          border: 'none',
                          borderRadius: '6px',
                          cursor: 'pointer',
                        }}
                      >
                        상담일지
                      </button>

                      <button
                        type="button"
                        onClick={() => setDetailTab('prescription')}
                        style={{
                          backgroundColor: detailTab === 'prescription' ? '#2563eb' : '#e5e7eb',
                          color: detailTab === 'prescription' ? 'white' : 'black',
                          padding: '10px 20px',
                          border: 'none',
                          borderRadius: '6px',
                          cursor: 'pointer',
                        }}
                      >
                        처방전
                      </button>
                    </div>

                    {detailTab === 'consultation' && (
                      <div>
                        <p>환자명: {selectedRecord.patientName}</p>
                        <p>상담 날짜: {selectedRecord.createdAt?.slice(0, 10)}</p>
                        <p>증상: {selectedRecord.symptoms}</p>

                        <h4>선택한 병증</h4>
                        {selectedRecord.selectedCandidates?.length > 0 ? (
                          <ul>
                            {selectedRecord.selectedCandidates.map((name) => (
                              <li key={name}>{name}</li>
                            ))}
                          </ul>
                        ) : (
                          <p>선택한 병증이 없습니다.</p>
                        )}

                        <h4>추가 기록</h4>
                        <p>{selectedRecord.additionalNotes || '-'}</p>
                      </div>
                    )}


                    {detailTab === 'prescription' && (
                      <div>
                        <h4>처방전 정보</h4>

                        {prescriptionRecords
                          .filter(
                            (prescription) =>
                              prescription.consultationId === selectedRecord.id
                          )
                          .map((prescription) => (
                            <div
                              key={prescription.id}
                              style={{
                                border: '1px solid #ddd',
                                borderRadius: '8px',
                                padding: '16px',
                                marginBottom: '12px',
                              }}
                            >
                              <p>처방명: {prescription.prescriptionName}</p>
                              <p>작성 날짜: {prescription.createdAt?.slice(0, 10)}</p>
                              <p>상태: {prescription.status}</p>

                              <h4>약재 구성</h4>

                              <table style={{ width: '100%' }}>
                                <thead>
                                  <tr>
                                    <th>약재명</th>
                                    <th>용량(g)</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {prescription.herbs.map((herb, index) => (
                                    <tr key={index}>
                                      <td>{herb.name}</td>
                                      <td>{herb.amount}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ))}

                        {!prescriptionRecords.some(
                          (prescription) =>
                            prescription.consultationId === selectedRecord.id
                        ) && (
                          <p>아직 작성된 처방전이 없습니다.</p>
                        )}
                      </div>
                    )}


                    <button
                      type="button"
                      onClick={() => {
                        setSelectedRecord(null)
                        setDetailTab('consultation')
                      }}
                      style={{ marginTop: '20px' }}
                    >
                      닫기
                    </button>

                  </div>
                </div>
              )}
            </div>
          )}


          {detailPatient && (
            <div
              style={{
                position: 'fixed',
                inset: 0,
                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 1000,
              }}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-label="환자 상세정보"
                style={{
                  backgroundColor: 'white',
                  padding: '24px',
                  borderRadius: '10px',
                  width: '420px',
                  maxWidth: '90%',
                }}
              >
                <h3>환자 상세정보</h3>
                <p>성명: {detailPatient.name}</p>
                <p>생년월일: {detailPatient.birthDate}</p>
                <p>연락처: {detailPatient.phone}</p>
                <p>주소: {detailPatient.address}</p>

                <h4>보호자 정보 (선택)</h4>
                <p>보호자 이름: {detailPatient.guardianName || '-'}</p>
                <p>관계: {detailPatient.guardianRelation || '-'}</p>
                <p>보호자 연락처: {detailPatient.guardianPhone || '-'}</p>

                <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
                <button type="button" onClick={registerWaitingPatient}>
                  상담대기등록
                </button>
                  <button type="button" onClick={() => setDetailPatient(null)}>
                    닫기
                  </button>
                </div>
              </div>
            </div>
          )}

          {editPatient && (
            <div
              style={{
                position: 'fixed',
                inset: 0,
                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 1000,
              }}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-label="환자 정보 수정"
                style={{
                  backgroundColor: 'white',
                  padding: '24px',
                  borderRadius: '10px',
                  width: '420px',
                  maxWidth: '90%',
                  maxHeight: '85vh',
                  overflowY: 'auto',
                }}
              >
                <h3>환자 정보 수정</h3>

                <div style={{ display: 'grid', gap: '12px' }}>
                  {[
                    ['name', '성명 (필수)', 'text'],
                    ['birthDate', '생년월일 (필수)', 'date'],
                    ['phone', '연락처 (필수)', 'tel'],
                    ['address', '주소 (필수)', 'text'],
                    ['guardianName', '보호자 이름', 'text'],
                    ['guardianRelation', '관계', 'text'],
                    ['guardianPhone', '보호자 연락처', 'tel'],
                  ].map(([name, label, type]) => (
                    <label key={name}>
                      {label}
                      <input
                        type={type}
                        name={name}
                        value={editPatient[name] || ''}
                        onChange={handleEditChange}
                      />
                    </label>
                  ))}
                </div>

                <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
                  <button type="button" onClick={saveEditedPatient}>
                    저장
                  </button>
                  <button type="button" onClick={() => setEditPatient(null)}>
                    취소
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
