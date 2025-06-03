// insurance.js
window.addEventListener("DOMContentLoaded", () => {
  const data = JSON.parse(localStorage.getItem("eligibilityData") || "{}");

  const subInput = document.getElementById("subscriber-id");
  const dobInput = document.getElementById("dob");

  if (subInput && data.subscriberId) subInput.value = data.subscriberId;
  if (dobInput && data.dob) dobInput.value = data.dob;

  const submitBtn = document.getElementById("submit-subscriber");
  if (submitBtn) {
    submitBtn.addEventListener("click", () => {
      const getBenefitText = (label) => {
        const items = document.querySelectorAll(".info-item");
        for (const item of items) {
          const labelEl = item.querySelector(".info-label");
          const valueEl = item.querySelector(".info-value");
          if (labelEl && valueEl && labelEl.textContent.trim().toLowerCase() === label.toLowerCase()) {
            return valueEl.textContent.trim();
          }
        }
        return "";
      };

      const orthoTable = document.querySelector("#ortho-table");
      const orthoData = [];

      if (orthoTable) {
        const rows = orthoTable.querySelectorAll("tbody tr");
        rows.forEach(row => {
          const cols = row.querySelectorAll("td");
          if (cols.length >= 7) {
            orthoData.push({
              code: cols[0].textContent.trim(),
              description: cols[1].textContent.trim(),
              ageRange: cols[2].textContent.trim(),
              coinsurance: cols[3].textContent.trim(),
              deductible: cols[4].textContent.trim(),
              waitingPeriod: cols[5].textContent.trim(),
              status: cols[6].textContent.trim()
            });
          }
        });
      }

      const insuranceData = {
        planName: "Premium Plus Plan",
        verifiedBy: "John Smith",
        lastExamDate: "2024-12-01",
        codeHistory: "D0120, D0140, D0150, D0180",
        deductible: getBenefitText("Deductible"),
        maximum: getBenefitText("Maximum"),
        orthoMax: getBenefitText("Orthodontia Max"),
        orthoProcedures: orthoData
      };

      const oldData = JSON.parse(localStorage.getItem("eligibilityData") || "{}");
      const merged = { ...oldData, ...insuranceData };
      localStorage.setItem("eligibilityData", JSON.stringify(merged));

      window.location.href = "index.html";
    });
  }
});
