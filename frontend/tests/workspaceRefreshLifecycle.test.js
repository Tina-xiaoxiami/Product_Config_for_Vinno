import assert from 'node:assert/strict'
import test from 'node:test'
import { createRenderer, defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { useWorkspaceRefresh } from '../src/utils/useWorkspaceRefresh.js'

function memoryRenderer() {
  const remove = node => {
    if (!node.parent) return
    const siblings = node.parent.children
    siblings.splice(siblings.indexOf(node), 1)
    node.parent = null
  }
  return createRenderer({
    createElement: type => ({ type, children: [] }),
    createText: text => ({ text }), createComment: text => ({ text }),
    insert(node, parent, anchor) {
      remove(node); node.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, node)
    },
    remove, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
    setText: (node, text) => { node.text = text },
    setElementText: (node, text) => { node.text = text; node.children = [] },
    patchProp() {}
  })
}

test('a late-mounted editor refreshes on its first return through a retained parent', async () => {
  const active = ref(true), editorVisible = ref(false)
  let reads = 0
  const Editor = defineComponent({ setup() { useWorkspaceRefresh(() => { reads++ }); return () => h('span') } })
  const Page = defineComponent({ setup: () => () => h('div', editorVisible.value ? [h(Editor)] : []) })
  const Other = defineComponent({ render: () => h('aside') })
  const app = memoryRenderer().createApp({ render: () => h(KeepAlive, null, { default: () => active.value ? h(Page) : h(Other) }) })
  app.mount({ children: [] })
  try {
    await nextTick()
    editorVisible.value = true; await nextTick()
    assert.equal(reads, 1)
    active.value = false; await nextTick()
    active.value = true; await nextTick()
    assert.equal(reads, 2)
  } finally { app.unmount() }
})
