#!/usr/bin/env node
/**
 * engine/skills/recommend.cjs — Project Tech Stack & Skill Recommender.
 *
 * Inspects projects in C:\Projects (or any specified project directory),
 * analyzes tech stacks, dependencies, and past error history, and computes
 * an optimal skill recommendation matrix with confidence scores and rationale.
 *
 * Usage:
 *   node engine/skills/recommend.cjs                     # Analyze all projects
 *   node engine/skills/recommend.cjs --project=phone-claude # Analyze one project
 *   node engine/skills/recommend.cjs --apply=phone-claude   # Apply recommendations
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.resolve(__dirname, '..', '..');
const STORAGE = path.join(ROOT, 'storage');
const MANIFEST_FILE = path.join(STORAGE, 'skills-manifest.json');
const CONFIG_FILE = path.join(STORAGE, 'skills-config.json');
const CANDIDATES_FILE = path.join(STORAGE, 'candidates.jsonl');

const PROJECTS_DIR = 'C:\\Projects';

function loadSkillsManifest() {
  if (!fs.existsSync(MANIFEST_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(MANIFEST_FILE, 'utf8'));
  } catch (_) {
    return {};
  }
}

function loadSkillsConfig() {
  if (!fs.existsSync(CONFIG_FILE)) return { globalEnabled: {}, projectOverrides: {} };
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
  } catch (_) {
    return { globalEnabled: {}, projectOverrides: {} };
  }
}

function saveSkillsConfig(config) {
  if (!fs.existsSync(STORAGE)) fs.mkdirSync(STORAGE, { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), 'utf8');
}

function analyzeProjectTechStack(projectPath) {
  const info = {
    path: projectPath,
    name: path.basename(projectPath),
    exists: fs.existsSync(projectPath),
    languages: new Set(),
    frameworks: new Set(),
    libraries: new Set(),
    traits: new Set(),
    dependencies: {},
    errorCount: 0
  };

  if (!info.exists) return info;

  // Check package.json
  const pkgPath = path.join(projectPath, 'package.json');
  if (fs.existsSync(pkgPath)) {
    info.languages.add('JavaScript');
    try {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
      const allDeps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
      info.dependencies = allDeps;

      if (allDeps.typescript || fs.existsSync(path.join(projectPath, 'tsconfig.json'))) {
        info.languages.add('TypeScript');
      }
      if (allDeps.react || allDeps['react-dom']) info.frameworks.add('React');
      if (allDeps.next) info.frameworks.add('Next.js');
      if (allDeps.vue) info.frameworks.add('Vue');
      if (allDeps.svelte) info.frameworks.add('Svelte');
      if (allDeps.tailwindcss || allDeps['@tailwindcss/postcss']) {
        info.frameworks.add('TailwindCSS');
        info.traits.add('tailwind');
      }
      if (allDeps.three || allDeps['@react-three/fiber']) {
        info.libraries.add('Three.js');
        info.traits.add('3d-graphics');
      }
      if (allDeps['framer-motion'] || allDeps.gsap || allDeps['lucide-react']) {
        info.libraries.add('Animation/Icons');
        info.traits.add('animations');
      }
      if (allDeps.zustand || allDeps.redux || allDeps['@reduxjs/toolkit']) {
        info.libraries.add('Zustand/State');
        info.traits.add('state-management');
      }
      if (allDeps.stripe || allDeps['@stripe/stripe-js']) {
        info.libraries.add('Stripe');
        info.traits.add('payments');
      }
      if (allDeps['@clerk/nextjs'] || allDeps['@clerk/clerk-sdk-node'] || allDeps.next_auth) {
        info.libraries.add('Clerk/Auth');
        info.traits.add('authentication');
      }
      if (allDeps.playwright || allDeps['@playwright/test'] || allDeps.jest || allDeps.vitest) {
        info.libraries.add('Testing Suite');
        info.traits.add('testing');
      }
      if (allDeps.express || allDeps.fastify || allDeps.koa) {
        info.frameworks.add('Node Server');
        info.traits.add('backend-api');
      }
    } catch (_) {}
  }

  // Check Python environment
  if (fs.existsSync(path.join(projectPath, 'requirements.txt')) || fs.existsSync(path.join(projectPath, 'pyproject.toml')) || fs.existsSync(path.join(projectPath, 'Pipfile'))) {
    info.languages.add('Python');
    const reqPath = path.join(projectPath, 'requirements.txt');
    if (fs.existsSync(reqPath)) {
      try {
        const reqs = fs.readFileSync(reqPath, 'utf8');
        if (reqs.includes('fastapi')) info.frameworks.add('FastAPI');
        if (reqs.includes('flask')) info.frameworks.add('Flask');
        if (reqs.includes('django')) info.frameworks.add('Django');
        if (reqs.includes('torch') || reqs.includes('tensorflow')) info.libraries.add('ML/AI');
        if (reqs.includes('pytest')) info.traits.add('testing');
      } catch (_) {}
    }
  }

  // Check Rust / Go / Shell
  if (fs.existsSync(path.join(projectPath, 'Cargo.toml'))) info.languages.add('Rust');
  if (fs.existsSync(path.join(projectPath, 'go.mod'))) info.languages.add('Go');
  if (fs.existsSync(path.join(projectPath, 'Dockerfile'))) info.traits.add('docker');

  // Check UI presence
  const hasAppDir = fs.existsSync(path.join(projectPath, 'app')) || fs.existsSync(path.join(projectPath, 'src', 'app')) || fs.existsSync(path.join(projectPath, 'pages'));
  const hasComponents = fs.existsSync(path.join(projectPath, 'components')) || fs.existsSync(path.join(projectPath, 'src', 'components'));
  if (hasAppDir || hasComponents || info.frameworks.has('React') || info.frameworks.has('Next.js')) {
    info.traits.add('web-ui');
  }

  // Error count from candidates
  if (fs.existsSync(CANDIDATES_FILE)) {
    try {
      const lines = fs.readFileSync(CANDIDATES_FILE, 'utf8').trim().split('\n').filter(Boolean);
      for (const l of lines) {
        const c = JSON.parse(l);
        if (c.repo && (c.repo.toLowerCase().includes(info.name.toLowerCase()) || info.name.toLowerCase().includes(c.repo.toLowerCase()))) {
          info.errorCount++;
        }
      }
    } catch (_) {}
  }

  return {
    ...info,
    languages: Array.from(info.languages),
    frameworks: Array.from(info.frameworks),
    libraries: Array.from(info.libraries),
    traits: Array.from(info.traits)
  };
}

function recommendSkillsForProject(projectPath) {
  const tech = analyzeProjectTechStack(projectPath);
  const manifest = loadSkillsManifest();
  const config = loadSkillsConfig();
  const overrides = config.projectOverrides[projectPath] || {};

  const recommendations = [];

  for (const [id, skill] of Object.entries(manifest)) {
    let score = 50; // base score
    const reasons = [];

    // Core universal skills always get a boost
    const universalSkills = ['preflight', 'blindspot', 'install-anti-slop', 'wes-voice', 'harden', 'dashclaw-platform-intelligence'];
    if (universalSkills.includes(id)) {
      score += 25;
      reasons.push('Essential safety, voice, and quality discipline');
    }

    // UI & Design Matching
    if (tech.traits.includes('web-ui') || tech.frameworks.includes('React') || tech.frameworks.includes('Next.js')) {
      if (id.includes('tailwind') && tech.traits.includes('tailwind')) {
        score += 40;
        reasons.push('Project uses TailwindCSS styling system');
      }
      if (id.includes('ui-animation') || id.includes('animate')) {
        score += 30;
        reasons.push('UI components detected for animation smoothing');
      }
      if (id.includes('frontend') || id.includes('impeccable') || id.includes('web-design') || id.includes('accessibility')) {
        score += 35;
        reasons.push('Active web application interface surface');
      }
      if (id.includes('zustand') && tech.traits.includes('state-management')) {
        score += 40;
        reasons.push('Zustand/state management detected in dependencies');
      }
    }

    // 3D & Graphics Matching
    if (tech.traits.includes('3d-graphics') && (id.includes('threejs') || id.includes('animate'))) {
      score += 45;
      reasons.push('Three.js / WebGL 3D canvas pipeline present');
    }

    // Auth & Payments Matching
    if ((tech.traits.includes('payments') || tech.traits.includes('authentication')) && (id.includes('secrets') || id.includes('audit') || id.includes('harden') || id.includes('blindspot'))) {
      score += 40;
      reasons.push('Auth & payment transaction flows require strict security');
    }

    // Media & Video Matching
    if (tech.name.toLowerCase().includes('video') || tech.name.toLowerCase().includes('medeo') || tech.name.toLowerCase().includes('media')) {
      if (id.includes('video') || id.includes('audio') || id.includes('animate')) {
        score += 45;
        reasons.push('Media editing & render pipeline matched');
      }
    }

    // High Error History Boost
    if (tech.errorCount > 10 && (id.includes('review') || id.includes('audit') || id.includes('critique') || id.includes('verify') || id.includes('de-vibe'))) {
      score += 25;
      reasons.push(`History of ${tech.errorCount} recorded deviations/assumptions`);
    }

    // Status: Recommended if score >= 75
    const isRecommended = score >= 75;
    const isGloballyEnabled = config.globalEnabled[id] !== false;
    const isProjectEnabled = overrides[id] !== undefined ? overrides[id] : (isGloballyEnabled && isRecommended);

    recommendations.push({
      skillId: id,
      skillName: skill.name,
      category: skill.category,
      description: skill.description,
      score,
      reasons,
      recommended: isRecommended,
      globallyEnabled: isGloballyEnabled,
      activeForProject: isProjectEnabled
    });
  }

  // Sort by score descending
  recommendations.sort((a, b) => b.score - a.score);

  return {
    project: tech,
    recommendations,
    recommendedCount: recommendations.filter(r => r.recommended).length,
    activeCount: recommendations.filter(r => r.activeForProject).length
  };
}

function listAllProjectsWithRecommendations() {
  const results = [];
  if (!fs.existsSync(PROJECTS_DIR)) return results;

  const entries = fs.readdirSync(PROJECTS_DIR, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;

    const fullPath = path.join(PROJECTS_DIR, entry.name);
    try {
      const rec = recommendSkillsForProject(fullPath);
      results.push({
        name: entry.name,
        path: fullPath,
        tech: rec.project,
        recommendedCount: rec.recommendedCount,
        activeCount: rec.activeCount,
        topRecommendations: rec.recommendations.filter(r => r.recommended).slice(0, 5)
      });
    } catch (_) {}
  }

  return results;
}

function applyProjectRecommendations(projectPath) {
  const rec = recommendSkillsForProject(projectPath);
  const config = loadSkillsConfig();

  if (!config.projectOverrides[projectPath]) {
    config.projectOverrides[projectPath] = {};
  }

  for (const r of rec.recommendations) {
    config.projectOverrides[projectPath][r.skillId] = r.recommended;
  }

  saveSkillsConfig(config);
  console.log(`[Skills] Applied ${rec.recommendedCount} recommended skills to ${projectPath}`);
  return config;
}

function toggleSkill(skillId, enabled, projectPath = null) {
  const config = loadSkillsConfig();
  if (projectPath) {
    if (!config.projectOverrides[projectPath]) {
      config.projectOverrides[projectPath] = {};
    }
    config.projectOverrides[projectPath][skillId] = Boolean(enabled);
  } else {
    config.globalEnabled[skillId] = Boolean(enabled);
  }
  saveSkillsConfig(config);
  return config;
}

if (require.main === module) {
  const projectArg = process.argv.find(a => a.startsWith('--project='));
  const applyArg = process.argv.find(a => a.startsWith('--apply='));

  if (applyArg) {
    const pName = applyArg.split('=')[1];
    const targetPath = path.isAbsolute(pName) ? pName : path.join(PROJECTS_DIR, pName);
    applyProjectRecommendations(targetPath);
  } else if (projectArg) {
    const pName = projectArg.split('=')[1];
    const targetPath = path.isAbsolute(pName) ? pName : path.join(PROJECTS_DIR, pName);
    const rec = recommendSkillsForProject(targetPath);
    console.log(`=== Skill Recommendations for ${rec.project.name} ===`);
    console.log(`Languages:   ${rec.project.languages.join(', ') || 'N/A'}`);
    console.log(`Frameworks:  ${rec.project.frameworks.join(', ') || 'N/A'}`);
    console.log(`Traits:      ${rec.project.traits.join(', ') || 'N/A'}`);
    console.log(`Error Count: ${rec.project.errorCount}`);
    console.log(`\nTop Recommended Skills (${rec.recommendedCount}):`);
    for (const r of rec.recommendations.filter(x => x.recommended).slice(0, 10)) {
      console.log(`  ★ [${r.score}%] ${r.skillName} (${r.category})`);
      console.log(`    → ${r.reasons.join('; ')}`);
    }
  } else {
    const all = listAllProjectsWithRecommendations();
    console.log(`=== Analyzed ${all.length} Projects in ${PROJECTS_DIR} ===\n`);
    for (const p of all.slice(0, 8)) {
      console.log(`📁 ${p.name} [${p.tech.languages.join(', ') || 'N/A'}]`);
      console.log(`   ${p.recommendedCount} skills recommended, ${p.activeCount} active`);
    }
  }
}

module.exports = {
  analyzeProjectTechStack,
  recommendSkillsForProject,
  listAllProjectsWithRecommendations,
  applyProjectRecommendations,
  toggleSkill,
  loadSkillsManifest,
  loadSkillsConfig
};
