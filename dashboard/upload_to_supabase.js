const { createClient } = require('@supabase/supabase-js');
const fs = require('fs');

const supabaseUrl = 'https://nfmxwnuvbrozueedkwzo.supabase.co';
const supabaseServiceKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mbXh3bnV2YnJvenVlZWRrd3pvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MTg3MjE4MywiZXhwIjoyMDk3NDQ4MTgzfQ.Dmnq-7UrC1XWr63LsxApQCjcvVWZixJj8hhIiT2K4B4';

const supabase = createClient(supabaseUrl, supabaseServiceKey);

async function upload() {
  console.log("Reading data.json...");
  const data = JSON.parse(fs.readFileSync('./public/data.json', 'utf-8'));
  
  console.log(`Uploading ${data.length} articles to Supabase...`);
  
  for (const article of data) {
    const { error } = await supabase.from('articles').upsert({
      url: article.url,
      source: article.source,
      feed: article.feed,
      title: article.title,
      author: article.author,
      published: new Date(article.published).toISOString(),
      text: article.text,
      fetched_at: article.fetched_at,
      summary: article.summary,
      sentiment: article.sentiment,
      relevance_score: article.relevance_score,
      category: article.category,
      brands: article.brands || [],
      car_models: article.car_models || []
    }, { onConflict: 'url' });
    
    if (error) {
      console.error("Error inserting article:", article.title, error);
    }
  }
  
  console.log("Upload complete!");
}

upload();
