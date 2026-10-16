export function RelationGraph(nodes = []) {
  return `<div class="relation-graph"><div class="relation-center">当前对象</div><div class="relation-lines"></div>${nodes.map((node, index) => `<div class="relation-node node-${index + 1}"><span>${node.type}</span><strong>${node.name}</strong><small>${node.meta || ''}</small></div>`).join('')}</div>`;
}
