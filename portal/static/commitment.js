const commitmentDialog = document.querySelector('[data-commitment]');
if (commitmentDialog && typeof commitmentDialog.showModal === 'function') {
  commitmentDialog.removeAttribute('open');
  commitmentDialog.showModal();
  commitmentDialog.querySelector('h1').focus();
  commitmentDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    commitmentDialog.querySelector('[data-commitment-exit]').requestSubmit();
  });
}
