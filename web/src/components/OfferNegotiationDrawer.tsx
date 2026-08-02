import { useEffect, useMemo, useRef, useState } from 'react';
import {
  confirmOfferNegotiationProposal,
  createOfferNegotiationProposal,
  previewOfferNegotiation,
  getOfferNegotiationProposal,
  listOfferNegotiationProposals,
  listOfferComparisonDimensions,
  listOfferComparisonValues,
  OfferNegotiationError,
} from '@/services/offers';
import type { Offer, OfferComparisonDimension, OfferNegotiationBlock, OfferNegotiationProposal, OfferNegotiationPending, OfferNegotiationPreview, OfferNegotiationSnapshot } from '@/types/offer';

interface Props {
  open: boolean;
  offer: Offer;
  dimensionIds?: number[];
  onClose: () => void;
  draft?: OfferNegotiationDraft;
  onDraftChange?: (draft: OfferNegotiationDraft | null) => void;
  entrypoint?: 'ui' | 'pilot';
}

export interface OfferNegotiationDraft {
  attemptKey: string;
  confirmationKey: string;
  goal: string;
  concerns: string;
  scenario: string;
  resultUnknown: boolean;
  pendingOperation: PendingOperation;
  proposalId: number | null;
  selectedBlocks: string[];
  edits: Record<string, string>;
  dimensionIds: number[];
  sourceFingerprint: string | null;
  previewSnapshot: OfferNegotiationSnapshot | null;
  previewInputKey: string | null;
}

type BlockField = 'communication_goals' | 'clarification_questions' | 'talking_points' | 'preparation_checks';
type PendingOperation = 'generate' | 'confirm' | null;

const SECTIONS: Array<[BlockField, string]> = [
  ['communication_goals', '沟通目标'],
  ['clarification_questions', '待澄清问题'],
  ['talking_points', '建议表达'],
  ['preparation_checks', '沟通前检查项'],
];

function newKey(prefix: string): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${prefix}-${Date.now()}`;
}

function safeError(error: unknown): string {
  if (!(error instanceof OfferNegotiationError)) return '谈薪准备暂时不可用，请稍后重试。';
  if (error.code === 'offer_negotiation_provider_error') return 'AI 服务暂不可用，请使用原尝试重试。';
  if (error.code === 'offer_negotiation_unverifiable') return 'AI 建议未通过证据校验，请重新开始。';
  if (error.code === 'offer_negotiation_source_changed') return 'Offer 来源已变化，请查看历史记录。';
  if (error.status === 422) return '谈薪准备输入无法验证，请检查后重试。';
  if (error.status === 409) return '本次谈薪准备已发生冲突，请重新开始。';
  return '谈薪准备暂时不可用，请稍后重试。';
}

function isPending(value: OfferNegotiationProposal | OfferNegotiationPending): value is OfferNegotiationPending {
  return value.attempt_status === 'generating' || value.attempt_status === 'provider_unknown';
}

export default function OfferNegotiationDrawer({ open, offer, dimensionIds = [], onClose, draft, onDraftChange, entrypoint = 'ui' }: Props) {
  const [goal, setGoal] = useState(draft?.goal ?? '');
  const [concerns, setConcerns] = useState(draft?.concerns ?? '');
  const [scenario, setScenario] = useState(draft?.scenario ?? '');
  const [attemptKey, setAttemptKey] = useState(() => draft?.attemptKey ?? newKey('offer-negotiation'));
  const [confirmationKey, setConfirmationKey] = useState(() => draft?.confirmationKey ?? newKey('offer-negotiation-confirm'));
  const [proposal, setProposal] = useState<OfferNegotiationProposal | null>(null);
  const [history, setHistory] = useState<OfferNegotiationProposal[]>([]);
  const [selectedBlocks, setSelectedBlocks] = useState<string[]>(draft?.selectedBlocks ?? []);
  const [edits, setEdits] = useState<Record<string, string>>(draft?.edits ?? {});
  const [frozenDimensionIds] = useState<number[]>(() => [...(draft?.dimensionIds ?? dimensionIds)]);
  const [frozenPreview, setFrozenPreview] = useState<OfferNegotiationPreview | null>(() => (
    draft?.sourceFingerprint && draft.previewSnapshot
      ? { source_fingerprint: draft.sourceFingerprint, snapshot: draft.previewSnapshot }
      : null
  ));
  const [previewInputKey, setPreviewInputKey] = useState<string | null>(draft?.previewInputKey ?? null);
  const [dimensionFacts, setDimensionFacts] = useState<Array<OfferComparisonDimension & { value_text: string | null }>>([]);
  const [dimensionFactsState, setDimensionFactsState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busy, setBusy] = useState(false);
  const [resultUnknown, setResultUnknown] = useState(draft?.resultUnknown ?? false);
  const [error, setError] = useState<string | null>(null);
  const [pendingOperation, setPendingOperation] = useState<PendingOperation>(draft?.pendingOperation ?? null);
  const suppressDraftPersistence = useRef(false);
  const lastPersistedDraft = useRef<string | null>(null);

  useEffect(() => {
    if (!open) return;
    void Promise.all([
      listOfferNegotiationProposals(offer.id),
      draft?.proposalId ? getOfferNegotiationProposal(draft.proposalId) : Promise.resolve(null),
    ]).then(([items, restored]) => {
      setHistory(items);
      if (restored && 'proposal' in restored && restored.proposal) setProposal(restored);
    }).catch(() => setHistory([]));
  }, [draft?.proposalId, offer.id, open]);

  useEffect(() => {
    if (!open) return;
    setDimensionFactsState('loading');
    void Promise.all([listOfferComparisonDimensions(true), listOfferComparisonValues(offer.id)])
      .then(([dimensions, values]) => {
        const valuesById = new Map(values.map((value) => [value.dimension_id, value.value_text]));
        setDimensionFacts(dimensions.map((dimension) => ({
          ...dimension,
          value_text: valuesById.get(dimension.id) ?? null,
        })));
        setDimensionFactsState('ready');
      })
      .catch(() => {
        setDimensionFacts([]);
        setDimensionFactsState('error');
      });
  }, [offer.id, open]);

  useEffect(() => {
    if (!open || !onDraftChange) return;
    if (suppressDraftPersistence.current) {
      suppressDraftPersistence.current = false;
      return;
    }
    const nextDraft: OfferNegotiationDraft = {
      attemptKey,
      confirmationKey,
      goal,
      concerns,
      scenario,
      resultUnknown,
      pendingOperation,
      proposalId: proposal?.id ?? draft?.proposalId ?? null,
      selectedBlocks,
      edits,
      dimensionIds: frozenDimensionIds,
      sourceFingerprint: frozenPreview?.source_fingerprint ?? null,
      previewSnapshot: frozenPreview?.snapshot ?? null,
      previewInputKey,
    };
    const serialized = JSON.stringify(nextDraft);
    if (serialized === lastPersistedDraft.current) return;
    lastPersistedDraft.current = serialized;
    onDraftChange(nextDraft);
  }, [attemptKey, confirmationKey, concerns, edits, frozenDimensionIds, frozenPreview, goal, onDraftChange, open, pendingOperation, previewInputKey, proposal, resultUnknown, scenario, selectedBlocks]);

  const blocks = useMemo(() => {
    if (!proposal) return [];
    return SECTIONS.flatMap(([field]) => proposal.proposal[field]);
  }, [proposal]);

  if (!open) return null;
  const frozen = resultUnknown || busy;
  const hasBrief = Boolean(proposal?.brief);
  const dimensionFactsReady = frozenDimensionIds.length === 0 || (
    dimensionFactsState === 'ready'
    && frozenDimensionIds.every((id) => dimensionFacts.some((dimension) => dimension.id === id))
  );

  const currentInputKey = JSON.stringify({
    dimension_ids: [...frozenDimensionIds].sort((a, b) => a - b),
    goal,
    concerns,
    scenario,
  });
  const activePreview = frozenPreview && previewInputKey === currentInputKey ? frozenPreview : null;
  const frozenOffer = proposal?.input_snapshot.offer_snapshot ?? activePreview?.snapshot.offer_snapshot;
  const displayedOffer = frozenOffer ?? offer;
  const visibleDimensions = proposal?.input_snapshot.offer_snapshot.dimensions
    ?? activePreview?.snapshot.offer_snapshot.dimensions
    ?? frozenDimensionIds.map((id) => {
      const dimension = dimensionFacts.find((item) => item.id === id);
      return {
        path_id: `dimension_${id}`,
        label: dimension?.label ?? `维度 ${id}`,
        value_text: dimension?.value_text ?? null,
      };
    });
  const visibleBrief = proposal?.input_snapshot.user_brief ?? activePreview?.snapshot.user_brief;

  const generate = async (fromRetry = false) => {
    if ((frozen && !fromRetry) || !goal.trim() || !concerns.trim() || !scenario.trim()) return;
    setError(null);
    try {
      let preview = frozenPreview;
      if (!fromRetry && (!preview || previewInputKey !== currentInputKey)) {
        setBusy(true);
        preview = await previewOfferNegotiation(offer.id, {
          dimension_ids: [...frozenDimensionIds].sort((a, b) => a - b),
          goal,
          concerns,
          scenario,
        });
        setFrozenPreview(preview);
        setPreviewInputKey(currentInputKey);
        setError('已读取本次将发送给 AI 的冻结快照，请核对后再次点击生成。');
        return;
      }
      if (!preview) return;
      if (!window.confirm('本次填写的目标、顾虑和沟通场景将发送给 AI，是否继续？')) return;
      setBusy(true);
      const result = await createOfferNegotiationProposal(offer.id, {
        idempotency_key: attemptKey,
        dimension_ids: [...frozenDimensionIds].sort((a, b) => a - b),
        goal,
        concerns,
        scenario,
        source_fingerprint: preview.source_fingerprint,
      }, entrypoint);
      if (isPending(result)) {
        setResultUnknown(true);
        setPendingOperation('generate');
        setError('上次请求结果待确认，请使用原尝试重试；输入已冻结。');
      } else {
        setProposal(result);
        setSelectedBlocks([]);
        setEdits({});
        setResultUnknown(false);
        setPendingOperation(null);
        setAttemptKey(newKey('offer-negotiation'));
        setConfirmationKey(newKey('offer-negotiation-confirm'));
        setFrozenPreview(null);
        setPreviewInputKey(null);
        suppressDraftPersistence.current = true;
        onDraftChange?.(null);
      }
    } catch (caught) {
      const known = caught instanceof OfferNegotiationError;
      if (
        known &&
        (
          caught.code === 'offer_negotiation_provider_error' ||
          caught.status === 0 ||
          (caught.status >= 500 && caught.status <= 599 && caught.code == null)
        )
      ) {
        setResultUnknown(true);
        setPendingOperation('generate');
      } else {
        setResultUnknown(false);
        setPendingOperation(null);
        setAttemptKey(newKey('offer-negotiation'));
        setFrozenPreview(null);
        setPreviewInputKey(null);
      }
      setError(safeError(caught));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (fromRetry = false) => {
    if (!proposal || (frozen && !fromRetry) || hasBrief || selectedBlocks.length === 0) return;
    if (!window.confirm('确认保存选中的谈薪准备内容？')) return;
    setBusy(true);
    setError(null);
    try {
      const brief = await confirmOfferNegotiationProposal(proposal.id, {
        confirmation_key: confirmationKey,
        selected_blocks: selectedBlocks,
        edited_content: edits,
      }, entrypoint);
      setProposal((current) => current ? { ...current, brief } : current);
      setResultUnknown(false);
      setPendingOperation(null);
      suppressDraftPersistence.current = true;
      onDraftChange?.(null);
    } catch (caught) {
      if (caught instanceof OfferNegotiationError && caught.code === 'offer_negotiation_source_changed') {
        setProposal((current) => current ? { ...current, source_changed: true } : current);
      } else if (caught instanceof OfferNegotiationError && (
        caught.code === 'offer_negotiation_provider_error'
        || caught.status === 0
        || (caught.status >= 500 && caught.code == null)
      )) {
        setResultUnknown(true);
        setPendingOperation('confirm');
      }
      setError(safeError(caught));
    } finally {
      setBusy(false);
    }
  };

  const retry = () => {
    setError(null);
    setResultUnknown(false);
    if (pendingOperation === 'confirm') void confirm(true);
    else void generate(true);
  };

  return (
    <section aria-label="谈薪准备" data-testid="offer-negotiation-drawer">
      <header>
        <h2>为 {offer.company_name} 准备谈薪</h2>
        <p>只整理事实、问题和表达草稿，不替你决定接受或拒绝 Offer。</p>
        <button type="button" onClick={onClose}>关闭</button>
      </header>
      {proposal && (
        <p role="status">{proposal.source_changed ? '来源已变化，以下仅供历史查看。' : '已冻结 Offer 来源，可审阅引用。'}</p>
      )}
      {error && <p role="alert">{error}</p>}
      {resultUnknown && (
        <button type="button" onClick={retry} disabled={busy}>使用原尝试重试</button>
      )}
      <section aria-label="AI input facts" data-testid="offer-negotiation-input-facts">
        <h3>本次将使用的 Offer 事实</h3>
        <p>{proposal?.input_snapshot || activePreview ? '以下为本次冻结输入' : '当前 Offer 事实，尚未冻结'}</p>
        <dl>
          <div><dt>公司</dt><dd>{displayedOffer.company_name}</dd></div>
          <div><dt>职位</dt><dd>{displayedOffer.position_name}</dd></div>
          <div><dt>状态</dt><dd>{displayedOffer.status}</dd></div>
          <div><dt>月薪</dt><dd>{displayedOffer.base_monthly ?? '尚未填写'}</dd></div>
          <div><dt>计薪月数</dt><dd>{displayedOffer.months_per_year ?? '尚未填写'}</dd></div>
          <div><dt>签字费</dt><dd>{displayedOffer.signing_bonus ?? '尚未填写'}</dd></div>
          <div><dt>股权</dt><dd>{displayedOffer.equity || '尚未填写'}</dd></div>
          <div><dt>福利</dt><dd>{displayedOffer.perks || '尚未填写'}</dd></div>
          <div><dt>截止时间</dt><dd>{displayedOffer.deadline || '尚未填写'}</dd></div>
          <div><dt>备注</dt><dd>{displayedOffer.notes || '尚未填写'}</dd></div>
          {visibleBrief && (
            <>
              <div><dt>本次目标</dt><dd>{visibleBrief.goal}</dd></div>
              <div><dt>本次顾虑</dt><dd>{visibleBrief.concerns}</dd></div>
              <div><dt>沟通场景</dt><dd>{visibleBrief.scenario}</dd></div>
            </>
          )}
        </dl>
        {visibleDimensions.length > 0 && (
          <ul>
            {visibleDimensions.map((dimension) => (
              <li key={dimension.path_id}>{dimension.label}：{dimension.value_text?.trim() ? dimension.value_text : '尚未填写'}</li>
            ))}
          </ul>
        )}
      </section>
      {!proposal && (
        <fieldset disabled={frozen}>
          <label>本次沟通目标<input value={goal} onChange={(event) => setGoal(event.target.value)} /></label>
          <label>顾虑<textarea value={concerns} onChange={(event) => setConcerns(event.target.value)} /></label>
          <label>沟通场景<input value={scenario} onChange={(event) => setScenario(event.target.value)} /></label>
          <button
            type="button"
            data-testid="offer-negotiation-generate"
            onClick={() => void generate()}
            disabled={frozen || !dimensionFactsReady || !goal.trim() || !concerns.trim() || !scenario.trim()}
          >
            {activePreview ? '确认快照并生成谈薪准备草稿' : '预览本次 AI 输入'}
          </button>
        </fieldset>
      )}
      {dimensionFactsState === 'loading' && <p role="status">正在读取本次谈薪准备所需的 Offer 事实……</p>}
      {dimensionFactsState === 'error' && <p role="alert">Offer 自定义维度暂时无法读取，请稍后重试。</p>}
      {proposal && (
        <div aria-label="谈薪准备草稿">
          {proposal.proposal_status === 'safe_empty' ? (
            <p>目前没有可验证、可给出的谈薪准备建议。</p>
          ) : SECTIONS.map(([field, label]) => (
            <section key={field}>
              <h3>{label}</h3>
              {proposal.proposal[field].map((block: OfferNegotiationBlock) => {
                const selected = selectedBlocks.includes(block.id);
                return (
                  <article key={block.id}>
                    <label>
                      <input
                        type="checkbox"
                        disabled={frozen || hasBrief || proposal.source_changed}
                        checked={selected}
                        onChange={() => setSelectedBlocks((current) => selected ? current.filter((id) => id !== block.id) : [...current, block.id])}
                      />
                      {block.text}
                    </label>
                    <p>{block.rationale}</p>
                    {selected && (
                      <textarea
                        disabled={frozen || hasBrief || proposal.source_changed}
                        value={edits[block.id] ?? block.text}
                        onChange={(event) => setEdits((current) => ({ ...current, [block.id]: event.target.value }))}
                      />
                    )}
                    <div>
                      {block.evidence_refs.map((ref) => <code key={`${ref.source}-${ref.path}`}>{ref.path}: {ref.excerpt}</code>)}
                    </div>
                  </article>
                );
              })}
            </section>
          ))}
          {proposal.proposal_status !== 'safe_empty' && !hasBrief && !proposal.source_changed && (
            <button type="button" data-testid="offer-negotiation-confirm" onClick={() => void confirm()} disabled={frozen || selectedBlocks.length === 0}>确认保存谈薪准备</button>
          )}
          {hasBrief && (
            <section aria-label="saved negotiation brief">
              <p>已确认保存，以下是本次实际保存的内容：</p>
              {(proposal.brief?.edited_content.blocks ?? [])
                .filter((block) => proposal.brief?.selected_blocks.includes(block.id))
                .map((block) => (
                  <p key={block.id}>{proposal.brief?.edited_content.edits?.[block.id] ?? block.text}</p>
                ))}
            </section>
          )}
        </div>
      )}
      {history.length > 0 && (
        <section aria-label="历史谈薪准备">
          <h3>历史记录</h3>
          {history.map((item) => <button type="button" key={item.id} onClick={() => setProposal(item)}>查看 {item.id}</button>)}
        </section>
      )}
      {blocks.length === 0 && proposal?.proposal_status === 'safe_empty' && <p>未生成可验证内容，未保存任何谈薪准备记录。</p>}
    </section>
  );
}
