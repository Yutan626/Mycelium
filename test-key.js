   require("dotenv").config();
   const { Groq } = require("groq-sdk");
   const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

   groq.chat.completions
     .create({
       messages: [{ role: "user", content: "Say this if you are called 'I'm Working Bro.'" }],
       model: "openai/gpt-oss-20b",
     })
     .then((r) => console.log(r.choices[0].message.content))
     .catch((e) => console.error("Failed:", e.message));