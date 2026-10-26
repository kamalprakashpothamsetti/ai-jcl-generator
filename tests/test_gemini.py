import os
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    from google import genai

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("GEMINI ERROR: GEMINI_API_KEY is not set.")
        else:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents="Generate a simple IBM mainframe IEFBR14 JCL."
            )
            print("SUCCESS!")
            print(response.text)
    except Exception as e:
        print("GEMINI ERROR:")
        print(type(e).__name__)
        print(str(e))