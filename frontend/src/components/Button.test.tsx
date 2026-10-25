import { render, screen } from '@testing-library/react'

import { Button } from './ui'

/** Macht, was Chromes Uebersetzer tut: jeder Textknoten wird durch <font><font>…</font></font> ersetzt. */
function translateLikeChrome(root: Node) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  while (walker.nextNode()) texts.push(walker.currentNode as Text)
  for (const text of texts) {
    const outer = document.createElement('font')
    const inner = document.createElement('font')
    inner.textContent = text.data
    outer.appendChild(inner)
    text.replaceWith(outer)
  }
}

// nexcrate issue #23: each button turned on its spinner after Chrome had translated the page, and React tried to put
// the spinner before a text node that was no longer there. nexbeat's button has the same shape.
test('a translated button still shows its spinner', () => {
  const { rerender } = render(<Button>Test connection</Button>)
  translateLikeChrome(screen.getByRole('button'))

  rerender(<Button loading>Test connection</Button>)

  const button = screen.getByRole('button')
  expect(button.querySelector('svg.animate-spin')).not.toBeNull()
  expect(button).toBeDisabled()
  expect(button.textContent).toBe('Test connection')

  rerender(<Button>Test connection</Button>)
  expect(screen.getByRole('button').querySelector('svg.animate-spin')).toBeNull()
})
