import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import ContextPreviewResult from './ContextPreviewResult.jsx'
import positive from './fixtures/positive.json'
import negative from './fixtures/negative.json'
import uncertain from './fixtures/uncertain.json'
import word from './fixtures/word.json'

const examples = [
  { key: 'positive', label: '긍정·부정 혼합', response: positive },
  { key: 'negative', label: '증상 부정', response: negative },
  { key: 'uncertain', label: '존재 여부 불확실', response: uncertain },
  { key: 'word', label: '문서 속 단어 언급', response: word },
]

function ContextPreviewDemo() {
  const [selected, setSelected] = useState('positive')
  const current = examples.find(example => example.key === selected)
  return <main className="ctx-demo">
    <header className="ctx-demo-header">
      <div className="ctx-brand">한의결</div><span>AI 검색 화면 검증</span>
    </header>
    <div className="ctx-demo-content">
      <p className="ctx-eyebrow">저장된 실험 결과로 확인하기</p>
      <h1>증상 문맥에 따른 결과 표시</h1>
      <p className="ctx-demo-note">화면 개발용 예제입니다. 로그인·DB·AI 서버 호출과 상담 저장 기능은 연결되지 않았습니다.</p>
      <section className="ctx-example-panel" aria-label="예제 선택">
        <label htmlFor="ctx-example">검증할 예제</label>
        <select id="ctx-example" value={selected} onChange={event => setSelected(event.target.value)}>
          {examples.map(example => <option key={example.key} value={example.key}>{example.label}</option>)}
        </select>
        <h2 className="ctx-input-label">입력 문장</h2>
        <p className="ctx-input">{current.response.symptoms}</p>
      </section>
      <ContextPreviewResult response={current.response} />
    </div>
  </main>
}

createRoot(document.getElementById('root')).render(<StrictMode><ContextPreviewDemo /></StrictMode>)
