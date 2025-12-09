import requests

url = "https://proposal-generation-for-funding-production.up.railway.app/generate-proposal/"

# Option A: Send raw text
payload = {"report_text": "Our research shows that solar panels in Lahore..."}
response = requests.post(url, params=payload)

# Option B: Upload a file
# files = {'file': open('my_feasibility_report.txt', 'rb')}
# response = requests.post(url, files=files)

if response.status_code == 200:
    with open("proposal.pdf", "wb") as f:
        f.write(response.content)
    print("PDF saved successfully!")
else:
    print("Error:", response.text)