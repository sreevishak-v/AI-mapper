(function () {
  if (window.location.pathname.includes("insurance.html")) {
    const data = JSON.parse(localStorage.getItem("eligibilityData") || "{}");
    const subInput = document.getElementById("subscriber-id");

    subInput?.addEventListener("click", () => {
      if (data.subscriberId) {
        subInput.value = data.subscriberId;
      }
    });
  }
})();
