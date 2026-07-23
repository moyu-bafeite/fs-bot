import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const supabase = createClient(supabaseUrl, supabaseKey, {
  db: { schema: "meta_data" },
});

const STORAGE_BUCKET = "hkex-reports";

interface Filing {
  id: number;
  stock_code: string;
  filing_type: string;
  report_year: number | null;
  news_id: string;
  file_url: string;
  title: string;
}

async function downloadAndUpload(filing: Filing): Promise<string> {
  const resp = await fetch(filing.file_url, { redirect: "follow" });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${filing.file_url}`);
  }
  const fileBytes = new Uint8Array(await resp.arrayBuffer());

  const year = filing.report_year ?? "unknown";
  const path = `${filing.stock_code}/${filing.filing_type}/${year}_${filing.news_id}.pdf`;

  const { error } = await supabase.storage
    .from(STORAGE_BUCKET)
    .upload(path, fileBytes, {
      contentType: "application/pdf",
      upsert: true,
    });

  if (error) {
    throw new Error(`Storage upload failed: ${error.message}`);
  }

  return path;
}

async function logError(
  filingId: number,
  stockCode: string,
  message: string,
) {
  await supabase.from("filing_logs").insert({
    action: "download",
    filing_id: filingId,
    stock_code: stockCode,
    level: "error",
    message,
  });
}

Deno.serve(async (_req) => {
  const { data: filings, error: queryError } = await supabase
    .from("filings")
    .select("id, stock_code, filing_type, report_year, news_id, file_url, title")
    .eq("status", "pending")
    .limit(1);

  if (queryError) {
    return new Response(JSON.stringify({ error: queryError.message }), {
      status: 500,
    });
  }

  if (!filings || filings.length === 0) {
    return new Response(JSON.stringify({ message: "没有 pending 记录" }), {
      status: 200,
    });
  }

  const filing = filings[0] as Filing;
  console.log(
    `[download-pdf] 开始处理: id=${filing.id} stock=${filing.stock_code} title="${filing.title}"`,
  );

  try {
    const pdfPath = await downloadAndUpload(filing);
    console.log(
      `[download-pdf] 下载成功: id=${filing.id} path=${pdfPath}`,
    );

    await supabase
      .from("filings")
      .update({ status: "downloaded", pdf_path: pdfPath })
      .eq("id", filing.id);

    return new Response(
      JSON.stringify({
        message: "下载成功",
        filing_id: filing.id,
        pdf_path: pdfPath,
      }),
      { status: 200 },
    );
  } catch (e) {
    const errorMsg = e instanceof Error ? e.message : String(e);
    console.error(
      `[download-pdf] 下载失败: id=${filing.id} error=${errorMsg}`,
    );
    await supabase
      .from("filings")
      .update({ status: "failed" })
      .eq("id", filing.id);
    await logError(filing.id, filing.stock_code, errorMsg);

    return new Response(
      JSON.stringify({
        message: "下载失败",
        filing_id: filing.id,
        error: errorMsg,
      }),
      { status: 500 },
    );
  }
});
