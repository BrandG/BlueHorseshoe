export const meta = {
  name: 'indicator-why-believed',
  description: 'One agent per textbook indicator: why it is BELIEVED to work, why it fails on our daily-equity screen, and whether a different horizon / entry / exit could rescue it. Anchored on the measured edge_table.csv so it cannot hand-wave.',
  phases: [
    { title: 'Per-indicator', detail: 'belief vs measured edge vs rescue test, one agent each' },
    { title: 'Synthesis', detail: 'unified why-the-paradigm-fails + which indicators deserve a real rescue experiment' },
  ],
}

const EDGE = '/root/BlueHorseshoe/research/indicator_screen/edge_table.csv'
const DATASET = '/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv'
const RUNPY = 'cd /root/BlueHorseshoe && ./run.sh python'

// The 25 textbook signals from run_screen.py (exact names as they appear in edge_table.csv).
const INDICATORS = [
  'rsi_oversold(<30)', 'rsi_exit_oversold(x30up)', 'rsi_bull(>50)',
  'williams_oversold(<-80)', 'stoch_oversold(<20)', 'cci_oversold(<-100)',
  'cci_break(x+100up)', 'bb_lower_touch', 'bb_upper_break(x up)', 'macd_bull_cross',
  'roc_pos(>0)', 'adx_uptrend(>25,+DI)', 'donchian20_break', 'aroonosc_up(>50)',
  'obv_rising(10d)', 'cmf_pos(>0)', 'mfi_oversold(<20)', 'rvol_high(>1.5x)',
  'engulfing_bull', 'hammer', 'gap_up(>2%)', 'above_sma200', 'golden_cross',
  'sma50_reclaim(x up)', 'sma20_pullback_uptrend',
]

const CONTEXT = [
  'CONTEXT: An edge screen already measured each signal on 2000 US equities, 2016-2026, daily bars.',
  'Edge table: ' + EDGE + ' (columns: indicator,horizon,regime,n,mean_fwd,baseline,edge,t).',
  '"edge" = mean forward close-to-close return when the signal fires MINUS the unconditional baseline',
  '(every eligible bar = a random long entry) at the same horizon/regime. Baseline (just being long, all):',
  'h1 +0.44% / h5 +0.65% / h10 +1.23% / h20 +1.54%. So edge>0 with t>2 = beats being long; edge<0 = picks WORSE than random.',
  'Headline finding: trend/breakout signals are robustly ANTI-predictive (daily forward returns mean-revert);',
  'the only faint positive is deep-oversold at long horizons. Long-biased system; ~5-10d swing horizon is the house default.',
].join('\n')

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['indicator', 'measured', 'believed_mechanism', 'why_it_fails_here', 'best_horizon_regime', 'rescue_verdict', 'rescue_experiment', 'recommendation'],
  properties: {
    indicator: { type: 'string' },
    measured: { type: 'string', description: 'one-line summary of its edge numbers across horizons/regimes from the table' },
    believed_mechanism: { type: 'string', description: 'why practitioners believe it works (the theory/lore), with the timeframe/market it is traditionally used on' },
    why_it_fails_here: { type: 'string', description: 'mechanistic reason it underperforms on our daily liquid-equity screen (beta confound? regime mismatch? timeframe? crowding?)' },
    best_horizon_regime: { type: 'string', description: 'the single horizon+regime where it looks least-bad or actually positive, with the number' },
    rescue_verdict: { type: 'string', enum: ['dead', 'try-different-horizon', 'try-mean-reversion-exit', 'try-entry-distance', 'works-as-filter-only'] },
    rescue_experiment: { type: 'string', description: 'if not dead, the one concrete experiment that would confirm a rescue on our stack' },
    recommendation: { type: 'string', enum: ['drop', 'demote-to-zero', 'keep-as-filter', 'promote-to-rescue-test'] },
  },
}

phase('Per-indicator')
const findings = (await parallel(INDICATORS.map(ind => () => agent(
  CONTEXT + '\n\n' +
  'Your indicator: "' + ind + '". First run `grep -F ' + JSON.stringify(ind) + ' ' + EDGE + '` (via ' + RUNPY + ' or bash) to read its measured edge across all horizons and regimes. ' +
  'You MAY do light pandas checks on ' + DATASET + ' but do NOT run heavy backtests. ' +
  'Then: (1) summarize what the table says it does; (2) explain precisely why practitioners BELIEVE this indicator works and on what timeframe/market it is traditionally applied; ' +
  '(3) give the mechanistic reason it fails (or succeeds) on our daily liquid-equity swing screen; ' +
  '(4) identify the single best horizon+regime cell; (5) judge whether a different horizon, a mean-reversion (vs trend-continuation) exit, or an entry-distance conditioning could rescue it, and if so the one concrete experiment to confirm. Be quantitative, cite the table numbers. Final answer = JSON.',
  { label: ind.slice(0, 22), phase: 'Per-indicator', schema: SCHEMA }
)))).filter(Boolean)

phase('Synthesis')
const synth = await agent(
  'You have per-indicator analyses of why ~25 textbook indicators are believed to work and why they fail on our daily-equity screen.\n\n' +
  JSON.stringify(findings, null, 1) + '\n\n' +
  'Write the unified answer to "why do so many presumably powerful indicators produce no edge for us?": ' +
  '(1) the 2-4 root mechanisms that explain the whole pattern; (2) the SHORT list of indicators (if any) that earned a real rescue experiment, ranked, each with its one experiment; ' +
  '(3) the honest verdict on whether indicator-based daily-equity selection can be made to work at all, or whether the edge (per the realized-vs-signal gap) lives in discretion/exits/entry-selection instead. Be decisive; null results are findings.',
  { label: 'synthesis', phase: 'Synthesis' }
)

return { findings, synthesis: synth, count: findings.length }
