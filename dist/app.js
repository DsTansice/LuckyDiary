document.addEventListener('DOMContentLoaded', () => {
  const count = document.querySelector('.entry-count .count');
  if (count) {
    count.textContent = count.textContent.padStart(2, '0');
  }
});
