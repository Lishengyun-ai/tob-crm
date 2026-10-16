export function Timeline(items = []) {
  return `<div class="timeline">${items.map(item => `<div class="timeline-item"><span class="timeline-dot ${item.kind || ''}"></span><div><strong>${item.title}</strong><p>${item.text}</p><small>${item.time}</small></div></div>`).join('')}</div>`;
}
