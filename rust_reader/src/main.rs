//! Reads the job postings dataset used by the Python MCP server and prints
//! the postings that need a skill, plus a count per company.
//!
//!     cargo run -- Rust
//!     cargo run -- python ../data/job_postings.json

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::process;

use serde::Deserialize;

const DEFAULT_DATA_FILE: &str = "../data/job_postings.json";

#[derive(Debug, Deserialize)]
struct Dataset {
    postings: Vec<JobPosting>,
}

// Only the fields this program uses; serde ignores the rest.
#[derive(Debug, Deserialize)]
struct JobPosting {
    id: String,
    title: String,
    company: String,
    location: String,
    remote: bool,
    skills: Vec<String>,
}

impl JobPosting {
    /// Case-insensitive, same as the Python server.
    fn has_skill(&self, skill: &str) -> bool {
        self.skills.iter().any(|s| s.eq_ignore_ascii_case(skill))
    }
}

fn load(path: &str) -> Result<Vec<JobPosting>, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("could not read {path}: {e}"))?;
    let dataset: Dataset =
        serde_json::from_str(&text).map_err(|e| format!("invalid JSON in {path}: {e}"))?;
    Ok(dataset.postings)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let Some(skill) = args.get(1).map(|s| s.trim()).filter(|s| !s.is_empty()) else {
        eprintln!("usage: rust_reader <skill> [path-to-json]");
        process::exit(2);
    };
    let path = args.get(2).map(String::as_str).unwrap_or(DEFAULT_DATA_FILE);

    let postings = match load(path) {
        Ok(postings) => postings,
        Err(message) => {
            eprintln!("error: {message}");
            process::exit(1);
        }
    };

    let matches: Vec<&JobPosting> = postings.iter().filter(|p| p.has_skill(skill)).collect();
    if matches.is_empty() {
        println!("No postings need '{skill}'.");
        return;
    }

    println!(
        "{} of {} postings need '{skill}':\n",
        matches.len(),
        postings.len()
    );
    for p in &matches {
        let remote = if p.remote { " (remote)" } else { "" };
        println!(
            "  {}  {} at {}, {}{}",
            p.id, p.title, p.company, p.location, remote
        );
    }

    // BTreeMap keeps companies in alphabetical order.
    let mut per_company: BTreeMap<&str, usize> = BTreeMap::new();
    for p in &matches {
        *per_company.entry(p.company.as_str()).or_default() += 1;
    }
    println!("\nPostings per company:");
    for (company, count) in per_company {
        println!("  {count:>2}  {company}");
    }
}
