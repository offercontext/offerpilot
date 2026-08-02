import { useEffect, useMemo, useRef, useState } from 'react';
import {
  confirmOfferNegotiationProposal,
  createOfferNegotiationProposal,
  getOfferNegotiationProposal,
  listOfferNegotiationProposals,
  OfferNegotiationError,
} from '@/services/offers';
import type { Offer, OfferNegotiationBlock, OfferNegotiationProposal, OfferNegotiationPending } from '@/types/offer';

interface Props {
  open: boolean;
  offer: Offer;
  dimensionIds?: number[];
  onClose: () => void;
  draft?: OfferNegotiationDraft;
  onDraftChange?: (draft: OfferNegotiationDraft | null) => void;
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

export default function OfferNegotiationDrawer({ open, offer, dimensionIds = [], onClose, draft, onDraftChange }: Props) {
  const [goal, setGoal] = useState(draft?.goal ?? '');
  const [concerns, setConcerns] = useState(draft?.concerns ?? '');
  const [scenario, setScenario] = useState(draft?.scenario ?? '');
  const [attemptKey, setAttemptKey] = useState(() => draft?.attemptKey ?? newKey('offer-negotiation'));
  const [confirmationKey, setConfirmationKey] = useState(() => draft?.confirmationKey ?? newKey('offer-negotiation-confirm'));
  const [proposal, setProposal] = useState<OfferNegotiationProposal | null>(null);
  const [history, setHistory] = useState<OfferNegotiationProposal[]>([]);
  const [selectedBlocks, setSelectedBlocks] = useState<string[]>(draft?.selectedBlocks ?? []);
  const [edits, setEdits] = useState<Record<string, string>>(draft?.edits ?? {});
  const [busy, setBusy] = useState(false);
  const [resultUnknown, setResultUnknown] = useState(draft?.resultUnknown ?? false);
  const [error, setError] = useState<string | null>(null);
  const [pendingOperation, setPendingOperation] = useState<PendingOperation>(draft?.pendingOperation ?? null);
  const suppressDraftPersistence = useRef(false);

  useEffect(() => {
    if (!open) return;
    void Promise.all([
      listOfferNegotiationProposals(offer.id),
      draft?.proposalId ? getOfferNegotiationProposal(draft.proposalId) : Promise.resolve(null),
    ]).then(([items, restored]) => {
      setHistory(items);
      if (restored) setProposal(restored);
    }).catch(() => setHistory([]));
  }, [draft?.proposalId, offer.id, open]);

  useEffect(() => {
    if (!open || !onDraftChange) return;
    if (suppressDraftPersistence.current) {
      suppressDraftPersistence.current = false;
      return;
    }
    onDraftChange({
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
    });
  }, [attemptKey, confirmationKey, concerns, draft?.proposalId, edits, goal, onDraftChange, open, pendingOperation, proposal, resultUnknown, scenario, selectedBlocks]);

  const blocks = useMemo(() => {
    if (!proposal) return [];
    return SECTIONS.flatMap(([field]) => proposal.proposal[field]);
  }, [proposal]);

  if (!open) return null;
  const frozen = resultUnknown || busy;
  const hasBrief = Boolean(proposal?.brief);

  const generate = async (fromRetry = false) => {
    if ((frozen && !fromRetry) || !goal.trim() || !scenario.trim()) return;
    if (!window.confirm('本次填写的目标、顾虑和沟通场景将发送给 AI，是否继续？')) return;
    setBusy(true);
    setError(null);
    try {
      const result = await createOfferNegotiationProposal(offer.id, {
        idempotency_key: attemptKey,
        dimension_ids: [...dimensionIds].sort((a, b) => a - b),
        goal,
        concerns,
        scenario,
      });
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
      });
      setProposal((current) => current ? { ...current, brief } : current);
      setResultUnknown(false);
      setPendingOperation(null);
      suppressDraftPersistence.current = true;
      onDraftChange?.(null);
    } catch (caught) {
      if (caught instanceof OfferNegotiationError && (caught.code === 'offer_negotiation_provider_error' || caught.status === 0)) {
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
      {!proposal && (
        <fieldset disabled={frozen}>
          <label>本次沟通目标<input value={goal} onChange={(event) => setGoal(event.target.value)} /></label>
          <label>顾虑<textarea value={concerns} onChange={(event) => setConcerns(event.target.value)} /></label>
          <label>沟通场景<input value={scenario} onChange={(event) => setScenario(event.target.value)} /></label>
          <button
            type="button"
            data-testid="offer-negotiation-generate"
            onClick={() => void generate()}
            disabled={frozen || !goal.trim() || !scenario.trim()}
          >
            生成谈薪准备草稿
          </button>
        </fieldset>
      )}
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
          {hasBrief && <p>已确认保存，可在历史记录中只读查看。</p>}
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
