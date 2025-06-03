chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "extractData",
    title: "Extract Eligibility Data",
    contexts: ["page"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "extractData") {
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      function: () => {
        alert("Use the popup to extract data.");
      }
    });
  }
});
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "parsePdf") {
    // Handle PDF parsing if needed
    // You can add background processing here if required
  }
});
