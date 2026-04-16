const createDOMPurify = require('dompurify');
const { JSDOM } = require('jsdom');

const window = new JSDOM('').window;
const DOMPurify = createDOMPurify(window);

function sanitizeMarkdown(input) {
  if (typeof input !== 'string') return '';
  // Strip HTML tags to prevent XSS; allow markdown to pass through.
  return DOMPurify.sanitize(input, { ALLOWED_TAGS: [] });
}

module.exports = { sanitizeMarkdown };
