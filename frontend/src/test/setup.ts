import '@testing-library/jest-dom/vitest'

// jsdom does not implement Element.scrollTo, which the chat panel uses to
// follow new messages.
if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
  Object.defineProperty(Element.prototype, 'scrollTo', {
    value: () => undefined,
    writable: true,
  })
}
