export function ActionCard(action) {
  const status = action.status || '待执行';
  const primary = status === '待执行'
    ? `<button class="small-button" data-action="start" data-id="${action.id}">开始</button>`
    : status === '进行中'
      ? `<button class="small-button" data-action="complete" data-id="${action.id}">完成</button>`
      : '';
  const secondary = ['已完成', '已取消'].includes(status) ? '' : `<button class="small-button secondary-action" data-action="delay" data-id="${action.id}">延期</button><button class="small-button secondary-action" data-action="cancel" data-id="${action.id}">取消</button>`;
  return `<article class="action-card" data-customer-id="${action.customerId || ''}" data-project-id="${action.projectId || ''}" data-opportunity-id="${action.opportunityId || ''}" data-source-agent-id="${action.sourceAgentId || ''}"><div class="action-main"><span class="priority-dot ${action.priority === '高' ? 'high' : ''}"></span><div><h4>${action.title}</h4><p>${action.reason}</p></div></div><div class="action-meta"><span>${action.type}</span><span>${action.dueDate || '待安排'}</span><span class="action-status">${status}</span>${primary}${secondary}</div></article>`;
}
