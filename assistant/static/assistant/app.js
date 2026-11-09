const form = document.getElementById("ask-form");
const textarea = document.getElementById("ask-text");
const button = document.getElementById("ask-button");
const pending = document.getElementById("pending");

// Show the newest answer.
window.scrollTo(0, document.body.scrollHeight);

// Enter asks the question. Shift+Enter starts a new line.
textarea.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function fitToText() {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}
textarea.addEventListener("input", fitToText);

form.addEventListener("submit", () => {
  // readOnly rather than disabled: a disabled field would not be sent.
  textarea.readOnly = true;
  button.disabled = true;
  document.getElementById("pending-question").textContent = textarea.value;
  pending.hidden = false;
  window.scrollTo(0, document.body.scrollHeight);
});
