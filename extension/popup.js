document.querySelectorAll('.tab-button').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    
    button.classList.add('active');
    const tabId = button.getAttribute('data-tab') + 'Tab';
    document.getElementById(tabId).classList.add('active');
  });
});

document.getElementById('fileInput').addEventListener('change', (event) => {
  const file = event.target.files[0];
  const status = document.getElementById('pdfStatus');
  const parseBtn = document.getElementById('parseBtn');
  
  if (file) {
    status.textContent = `Selected: ${file.name}`;
    parseBtn.disabled = false;
  } else {
    status.textContent = 'No file selected';
    parseBtn.disabled = true;
  }
});

document.getElementById('parseBtn').addEventListener('click', async () => {
  const fileInput = document.getElementById('fileInput');
  const resultsDiv = document.getElementById('pdfResults');
  const file = fileInput.files[0];
  
  if (!file) {
    resultsDiv.innerHTML = '<span style="color:red">Please select a PDF file</span>';
    return;
  }

  resultsDiv.innerHTML = 'Parsing PDF...';

  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('http://localhost:8000/parse-pdf/', {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      throw new Error(`Server error: ${response.status}`);
    }
    
    const data = await response.json();
    if (data.status !== 'success') {
      throw new Error(data.error || 'Unknown error');
    }

    // Store parsed data
    localStorage.setItem(`eligibilityData_${file.name}`, JSON.stringify(data.data));

    // Display results
    const { mappedFields, tables } = data.data;
    let html = `<div class="file-result"><strong>${file.name}</strong><br>`;

    // Subscriber Info
    html += `
      <strong>Subscriber Info:</strong><br>
      Name: ${mappedFields.patientName || 'N/A'}<br>
      ID: ${mappedFields.subscriberId || 'N/A'}<br>
      DOB: ${mappedFields.subscriberDateOfBirth || 'N/A'}<br>
      Gender: ${mappedFields.gender || 'N/A'}<br>
      Relationship: ${mappedFields.subscriberRelationship || 'N/A'}<br>
      Coverage: ${mappedFields.effectiveDate || 'N/A'} to ${mappedFields.terminationDate || 'N/A'}<br><br>
    `;

    // Plan Info
    html += `
      <strong>Plan Info:</strong><br>
      Name: ${mappedFields.planName || 'N/A'}<br>
      Provider: ${mappedFields.payorName || 'N/A'}<br>
      Group: ${mappedFields.groupNumber || 'N/A'}<br>
      Plan Type: ${mappedFields.planType || 'N/A'}<br>
      Other Insurance: ${mappedFields.cob || 'N/A'}<br><br>
    `;

    // Benefits
    html += `
      <strong>Benefits:</strong><br>
      Individual Deductible: ${mappedFields.individualDeductible || 'N/A'}<br>
      Family Deductible: ${mappedFields.familyDeductible || 'N/A'}<br>
      Individual Maximum: ${mappedFields.individualMaximum || 'N/A'}<br>
      Orthodontics Maximum: ${mappedFields.orthodonticsMaximum || 'N/A'}<br><br>
    `;

    // Coinsurance Table
    if (mappedFields.coinsurance) {
      html += `
        <strong>Coinsurance Percentages:</strong><br>
        <table>
          <tr><th>Category</th><th>Percentage</th></tr>
          <tr><td>Diagnostic and Preventive</td><td>${mappedFields.coinsurance.diagnostic || 'N/A'}</td></tr>
          <tr><td>Basic Restorative</td><td>${mappedFields.coinsurance.basicRestorative || 'N/A'}</td></tr>
          <tr><td>Major Restorative</td><td>${mappedFields.coinsurance.majorRestorative || 'N/A'}</td></tr>
          <tr><td>Orthodontics</td><td>${mappedFields.coinsurance.orthodontics || 'N/A'}</td></tr>
        </table><br>
      `;
    }

    // Frequency Limitations Table
    if (mappedFields.frequencies) {
      html += `
        <strong>Frequency Limitations:</strong><br>
        <table>
          <tr><th>Procedure</th><th>Frequency</th></tr>
          <tr><td>Oral Exam</td><td>${mappedFields.frequencies.oralExam || 'N/A'}</td></tr>
          <tr><td>Full Mouth X-Rays</td><td>${mappedFields.frequencies.fullMouthXRays || 'N/A'}</td></tr>
          <tr><td>Bitewing X-Rays</td><td>${mappedFields.frequencies.bitewingXRays || 'N/A'}</td></tr>
          <tr><td>Adult Cleaning</td><td>${mappedFields.frequencies.adultCleaning || 'N/A'}</td></tr>
          <tr><td>Topical Fluoride</td><td>${mappedFields.frequencies.topicalFluoride || 'N/A'}</td></tr>
          <tr><td>Topical Sealant</td><td>${mappedFields.frequencies.topicalSealant || 'N/A'}</td></tr>
          <tr><td>Crown</td><td>${mappedFields.frequencies.crown || 'N/A'}</td></tr>
          <tr><td>Bridge Work</td><td>${mappedFields.frequencies.bridgeWork || 'N/A'}</td></tr>
        </table><br>
      `;
    }

    // Preauthorization
    html += `
      <strong>Preauthorization:</strong><br>
      ${mappedFields.preAuthRequired || 'N/A'}<br>
    `;

    html += '</div>';
    resultsDiv.innerHTML = html;

  } catch (error) {
    resultsDiv.innerHTML = `<span style="color:red">Error: ${error.message}</span>`;
    console.error('PDF parsing error:', error);
  }
});

document.getElementById('closeBtn').addEventListener('click', () => {
  chrome.runtime.sendMessage({ action: 'closeExtensionWindow' });
});