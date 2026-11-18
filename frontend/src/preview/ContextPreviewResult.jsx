import { useState } from 'react'
import './context-preview.css'

const routeTitles = {
  CANDIDATE_REVIEW: '검색 후보 검토',
  CONFIRM_INTERPRETATION: '증상 표현 확인',
  REVIEW_INPUT: '증상 입력 재검토',
}

export function validPreview(response) {
  if (!response || !Object.hasOwn(routeTitles, response.route) || typeof response.message !== 'string') return false
  if (typeof response.symptoms !== 'string' || !Array.isArray(response.candidates) || !Array.isArray(response.reviewMentions)) return false
  if (!Number.isInteger(response.total) || response.total !== response.candidates.length || response.historySaved !== false) return false
  if (response.route !== 'CANDIDATE_REVIEW' && response.total !== 0) return false
  const characters = Array.from(response.symptoms)
  return response.candidates.every((candidate, index) =>
    Number.isInteger(candidate.id) && candidate.rank === index + 1 && typeof candidate.name === 'string'
    && Array.isArray(candidate.keywordEvidence)
    && (candidate.semanticEvidence === null || typeof candidate.semanticEvidence === 'object'))
    && response.reviewMentions.every(mention =>
      Number.isInteger(mention.start) && Number.isInteger(mention.end)
      && mention.start >= 0 && mention.end > mention.start && mention.end <= characters.length
      && characters.slice(mention.start, mention.end).join('') === mention.source_text)
}

function Evidence({ candidate }) {
  const semantic = candidate.semanticEvidence
  return (
    <details className="ctx-evidence">
      <summary>검색 근거 보기</summary>
      <div className="ctx-evidence-body">
        <h4>키워드 근거</h4>
        {candidate.keywordEvidence.length === 0
          ? <p className="ctx-muted">이 후보에 연결된 긍정 증상 키워드 근거는 없습니다.</p>
          : <ul>{candidate.keywordEvidence.map((evidence, index) => (
            <li key={index}>
              입력 표현 <strong>“{evidence.matched_text}”</strong>
              <span className="ctx-muted"> · 등록 표현: {evidence.registered_term}</span>
            </li>
          ))}</ul>}
        <h4>의미 검색 근거</h4>
        {semantic?.excerpt ? <>
          <blockquote>{semantic.excerpt}</blockquote>
          <p className="ctx-source">출처: {semantic.source?.file || '원문 자료'}
            {semantic.source?.sheet && ` · ${semantic.source.sheet}`}
            {semantic.source?.row && ` · ${semantic.source.row}행`}
          </p>
        </> : <p className="ctx-muted">표시할 의미 검색 원문이 없습니다.</p>}
      </div>
    </details>
  )
}

function ResultBody({ response }) {
  const [showAll, setShowAll] = useState(false)
  const isCandidate = response.route === 'CANDIDATE_REVIEW'
  const visible = showAll ? response.candidates : response.candidates.slice(0, 3)
  return (
    <section className="ctx-result" aria-label="AI 검색 미리보기 결과">
      <header className="ctx-result-heading">
        <div><p className="ctx-eyebrow">분석 결과</p><h2>{routeTitles[response.route]}</h2></div>
        <span className={'ctx-badge ' + (isCandidate ? 'ctx-badge-green' : 'ctx-badge-amber')}>
          {isCandidate ? `후보 ${response.total}개` : '입력 확인 필요'}
        </span>
      </header>
      <p className="ctx-message" role="status">{response.message}</p>
      {!isCandidate && response.reviewMentions.length > 0 && <div className="ctx-review">
        <h3>확인할 표현</h3>
        <ul>{response.reviewMentions.map((mention, index) => (
          <li key={index}><strong>“{mention.source_text}”</strong> — 증상이 있는지 또는 어떤 의미인지 확인해주세요.</li>
        ))}</ul>
      </div>}
      {isCandidate && <>
        <p className="ctx-muted">검토 후보이며 확정 진단이 아닙니다. 각 후보의 입력 표현과 원문 근거를 확인해주세요.</p>
        <ol className="ctx-candidates">
          {visible.map(candidate => <li className="ctx-candidate" key={candidate.id}>
            <div className="ctx-candidate-heading">
              <span className="ctx-rank">{candidate.rank}</span><h3>{candidate.name}</h3>
            </div>
            <Evidence candidate={candidate} />
          </li>)}
        </ol>
        {response.total > 3 && <button type="button" className="ctx-more" aria-expanded={showAll}
          onClick={() => setShowAll(value => !value)}>
          {showAll ? '상위 3개만 보기' : `전체 ${response.total}개 후보 보기`}
        </button>}
        <p className="ctx-count">전체 {response.total}개 중 {visible.length}개 표시</p>
      </>}
      <footer className="ctx-result-footer">미리보기 · 상담 및 검색 이력에 저장되지 않았습니다.</footer>
    </section>
  )
}

export default function ContextPreviewResult({ response }) {
  if (!validPreview(response)) {
    return <section className="ctx-result" role="alert"><h2>결과를 표시할 수 없습니다.</h2><p>응답 형식을 확인한 뒤 다시 시도해주세요.</p></section>
  }
  // 다른 입력의 결과를 받을 때 펼친 목록과 근거를 초기화한다.
  return <ResultBody key={response.previewId + ':' + response.symptoms} response={response} />
}
