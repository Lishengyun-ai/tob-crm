export function ScoreCard({ label, value, caption = '', color = 'blue' }) {
  return `<article class="score-card"><div class="score-top"><span>${label}</span><strong class="${color}">${value}</strong></div><div class="score-track"><i class="${color}" style="width:${Math.min(100, Number(value) || 0)}%"></i></div><small>${caption}</small></article>`;
}
