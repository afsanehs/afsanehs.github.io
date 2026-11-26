(() => {
  // Back to top
  const toTop = document.querySelector('.to-top');
  const onScroll = () => toTop.classList.toggle('show', window.scrollY > 600);
  window.addEventListener('scroll', onScroll, { passive: true });
  toTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  onScroll();

  const box = document.querySelector('.lightbox');
  if (!box) return;

  // Lightbox
  const img = box.querySelector('.lb-stage img');
  const label = box.querySelector('.lb-label');
  const count = box.querySelector('.lb-count');
  const prevBtn = box.querySelector('.lb-prev');
  const nextBtn = box.querySelector('.lb-next');
  let set = [];
  let idx = 0;

  function show() {
    const a = set[idx];
    const thumb = a.querySelector('img');
    img.src = thumb ? (thumb.currentSrc || thumb.src) : a.dataset.small;
    img.alt = thumb ? thumb.alt : a.getAttribute('aria-label');
    const full = new Image();
    full.onload = () => { if (set[idx] === a) img.src = a.href; };
    full.src = a.href;
    count.textContent = `${idx + 1} of ${set.length}`;
    [set[idx - 1], set[idx + 1]].forEach((n) => { if (n) new Image().src = n.href; });
  }
  function step(d) {
    if (set.length < 2) return;
    idx = (idx + d + set.length) % set.length;
    show();
  }

  document.addEventListener('click', (e) => {
    const a = e.target.closest('.ph');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    const post = a.closest('.post');
    set = [...post.querySelectorAll('.ph')];
    idx = set.indexOf(a);
    label.textContent = post.dataset.label;
    prevBtn.hidden = nextBtn.hidden = set.length < 2;
    show();
    box.showModal();
  });

  prevBtn.addEventListener('click', () => step(-1));
  nextBtn.addEventListener('click', () => step(1));
  box.querySelector('.lb-close').addEventListener('click', () => box.close());
  let swiped = false;
  box.addEventListener('click', (e) => {
    if (swiped) { swiped = false; return; }
    if (e.target === box || e.target.classList.contains('lb-stage')) box.close();
  });
  box.addEventListener('close', () => { img.removeAttribute('src'); });
  document.addEventListener('keydown', (e) => {
    if (!box.open) return;
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
  });

  // Swipe left/right on touch screens
  let startX = null;
  box.addEventListener('pointerdown', (e) => { startX = e.clientX; swiped = false; });
  box.addEventListener('pointerup', (e) => {
    if (startX === null) return;
    const dx = e.clientX - startX;
    startX = null;
    if (Math.abs(dx) > 50) {
      swiped = true;
      step(dx < 0 ? 1 : -1);
    }
  });
})();
