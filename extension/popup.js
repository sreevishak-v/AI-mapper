document.addEventListener('DOMContentLoaded', () => {
  // Tab navigation
  document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
      
      button.classList.add('active');
      const tabId = button.getAttribute('data-tab') + 'Tab';
      document.getElementById(tabId).classList.add('active');
    });
  });

  // File input change handler
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

  // Parse button click handler
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
        throw new Error(`Server error: ${response.status}. Please check the server logs for details.`);
      }
      
      const data = await response.json();
      if (data.status !== 'success') {
        throw new Error(data.error || 'Unknown error');
      }

      localStorage.setItem(`eligibilityData_${file.name}`, JSON.stringify(data.data));

      // Debug the response data
      console.log('Full Response Data:', JSON.stringify(data, null, 2));
      console.log('data.data:', JSON.stringify(data.data, null, 2));
      console.log('data.data.rawData:', JSON.stringify(data.data.rawData, null, 2));
      console.log('data.data.procedure_codes:', JSON.stringify(data.data.procedure_codes, null, 2));

      const { mappedFields, rawData } = data.data;
      let html = `<div class="file-result"><strong>${file.name}</strong><br>`;

      // Basic Information
      html += `
        Subscriber ID: ${mappedFields.subscriberId || rawData.patient_info?.subscriber_id || 'N/A'}<br>
        Effective Date: ${mappedFields.effectiveDate || rawData.plan_info?.effective_date || 'N/A'}<br>
        Termination Date: ${mappedFields.terminationDate || rawData.plan_info?.termination_date || 'N/A'}<br>
        Carrier Name: ${mappedFields.payorName || rawData.plan_info?.insurance_provider || 'N/A'}<br><br>
      `;

      // Subscriber Info
      html += `
        <strong>Subscriber Info:</strong><br>
        Name: ${mappedFields.patientName || rawData.patient_info?.name || 'N/A'}<br>
        DOB: ${mappedFields.subscriberDateOfBirth || rawData.patient_info?.subscriber_dob || 'N/A'}<br>
        Gender: ${mappedFields.gender || rawData.patient_info?.gender || 'N/A'}<br>
        Relationship: ${mappedFields.subscriberRelationship || rawData.patient_info?.relationship || 'N/A'}<br><br>
      `;

      // Plan Info
      html += `
        <strong>Plan Info:</strong><br>
        Plan Name: ${mappedFields.planName || rawData.plan_info?.plan_name || 'N/A'}<br>
        Group Number: ${mappedFields.groupNumber || rawData.plan_info?.group_number || 'N/A'}<br>
        Insurance Type: ${mappedFields.insuranceType || rawData.plan_info?.insurance_type || 'N/A'}<br>
        Employer: ${mappedFields.employer || rawData.plan_info?.employer || 'N/A'}<br>
        Plan Reset Date: ${mappedFields.planResetDate || rawData.plan_info?.plan_reset_date || 'N/A'}<br>
        Plan Type: ${mappedFields.planType || rawData.plan_info?.plan_type || 'N/A'}<br>
        Benefits Coordination Method: ${mappedFields.benefitsCoordinationMethod || rawData.plan_info?.benefits_coordination_method || 'N/A'}<br>
        Verified Date: ${mappedFields.verifiedDate || rawData.plan_info?.verified_date || 'N/A'}<br>
        Participation Type: ${mappedFields.participationType || rawData.plan_info?.participation_type || 'N/A'}<br><br>
      `;

      // General Benefits
      const benefits = rawData.benefits || {};
      const deductible = benefits.deductible || {};
      const maximum = benefits.maximum || {};
      html += `
        <strong>General Benefits:</strong><br>
        Family Maximum: ${mappedFields.familyMaximum || maximum.family_total || 'N/A'}, Family Max. Remaining: ${mappedFields.familyMaxRemaining || maximum.family_remaining || 'N/A'}<br>
        Individual Maximum: ${mappedFields.individualMaximum || maximum.individual_total || 'N/A'}, Individual Max. Remaining: ${mappedFields.individualMaxRemaining || maximum.individual_remaining || 'N/A'}<br>
        Family Deductible: ${mappedFields.familyDeductible || deductible.family_total || 'N/A'}, Family Deductible Remaining: ${mappedFields.familyDeductibleRemaining || deductible.family_remaining || 'N/A'}<br>
        Individual Deductible: ${mappedFields.individualDeductible || deductible.individual_total || 'N/A'}, Individual Deductible Remaining: ${mappedFields.individualDeductibleRemaining || deductible.individual_remaining || 'N/A'}<br><br>
      `;

      // Coinsurance
      if (mappedFields.coinsurance || benefits.coinsurance) {
        const coinsurance = mappedFields.coinsurance || benefits.coinsurance || {};
        html += `
          <strong>Coinsurance Percentages:</strong><br>
          <table>
            <tr><th>Category</th><th>Percentage</th></tr>
            <tr><td>Diagnostic and Preventive</td><td>${coinsurance.diagnostic || 'N/A'}</td></tr>
            <tr><td>Basic Restorative</td><td>${coinsurance.basicRestorative || 'N/A'}</td></tr>
            <tr><td>Major Restorative</td><td>${coinsurance.majorRestorative || 'N/A'}</td></tr>
            <tr><td>Orthodontics</td><td>${coinsurance.orthodontics || 'N/A'}</td></tr>
          </table><br>
        `;
      }

      // Frequencies
      if (mappedFields.frequencies || benefits.frequencies) {
        const frequencies = mappedFields.frequencies || benefits.frequencies || {};
        html += `
          <strong>Frequency Limitations:</strong><br>
          <table>
            <tr><th>Procedure</th><th>Frequency</th></tr>
            <tr><td>Oral Exam</td><td>${frequencies.oralExam || 'N/A'}</td></tr>
            <tr><td>Full Mouth X-Rays</td><td>${frequencies.fullMouthXRays || 'N/A'}</td></tr>
            <tr><td>Bitewing X-Rays</td><td>${frequencies.bitewingXRays || 'N/A'}</td></tr>
            <tr><td>Adult Cleaning</td><td>${frequencies.adultCleaning || 'N/A'}</td></tr>
            <tr><td>Topical Fluoride</td><td>${frequencies.topicalFluoride || 'N/A'}</td></tr>
            <tr><td>Topical Sealant</td><td>${frequencies.topicalSealant || 'N/A'}</td></tr>
            <tr><td>Crown</td><td>${frequencies.crown || 'N/A'}</td></tr>
            <tr><td>Bridge Work</td><td>${frequencies.bridgeWork || 'N/A'}</td></tr>
          </table><br>
        `;
      }

      // Preauthorization
      html += `
        <strong>Preauthorization:</strong><br>
        ${mappedFields.preAuthRequired || benefits.pre_auth || 'N/A'}<br><br>
      `;

      // Last Procedures
      const lastProcedures = rawData.last_procedures || {};
      html += `<strong>Last Procedures:</strong><br>`;
      if (Object.keys(lastProcedures).length === 0) {
        html += `N/A<br><br>`;
      } else {
        for (const [key, value] of Object.entries(lastProcedures)) {
          html += `${key}: ${value}<br>`;
        }
        html += `<br>`;
      }

      // Procedure Codes - Try multiple sources
      let procedureCodes = data.data.procedure_codes || rawData.procedure_codes || rawData["Procedure Codes"] || {};
      console.log('Procedure Codes Data:', JSON.stringify(procedureCodes, null, 2));

      html += `<strong>Procedure Codes:</strong><br>`;
      if (Object.keys(procedureCodes).length === 0) {
        html += `No procedure codes found.<br><br>`;
      } else {
        for (const [code, details] of Object.entries(procedureCodes)) {
          html += `
            ${code}<br>
            <ul>
              ${details.Quadrant ? `<li>Quadrant: ${details.Quadrant}</li>` : ''}
              ${details.Total ? `<li>Total: ${details.Total}</li>` : ''}
              ${details["Member Responsibility"] ? `<li>Member Responsibility: ${details["Member Responsibility"]}</li>` : ''}
              ${details.History ? `<li>History: ${details.History}</li>` : ''}
              ${details.Note ? `<li>Note: ${details.Note}</li>` : ''}
            </ul>
          `;
        }
        html += `<br>`;
      }

      html += '</div>';
      resultsDiv.innerHTML = html;

    } catch (error) {
      resultsDiv.innerHTML = `<span style="color:red">Error: ${error.message}. Please check the server logs for details.</span>`;
      console.error('PDF parsing error:', error);
    }
  });

  // Close button handler
  document.getElementById('closeBtn').addEventListener('click', () => {
    chrome.runtime.sendMessage({ action: 'closeExtensionWindow' });
  });
});