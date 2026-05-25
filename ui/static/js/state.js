// --- state.js — shared DOM refs + globals (must load first) ---
var currentSessionId = null;

// DOM Elements
var sessionList = document.getElementById('sessionList');
var newSessionBtn = document.getElementById('newSessionBtn');
var featureInput = document.getElementById('featureInput');
var generateBtn = document.getElementById('generateBtn');
var autoExecuteCheck = document.getElementById('autoExecuteCheck');
var caseCountSelect = document.getElementById('caseCountSelect');

var welcomeState = document.getElementById('welcomeState');
var activeSessionState = document.getElementById('activeSessionState');
var activeSessionTitle = document.getElementById('activeSessionTitle');
var activeSessionStatus = document.getElementById('activeSessionStatus');
var testCasesContainer = document.getElementById('testCasesContainer');
var automationPrompt = document.getElementById('automationPrompt');
var runAutomationBtn = document.getElementById('runAutomationBtn');
var automationResultsContainer = document.getElementById('automationResultsContainer');

var sidebarToggle = document.getElementById('sidebarToggle');
var mainSidebar = document.getElementById('mainSidebar');
var navToReportsBtn = document.getElementById('navToReportsBtn');

// Nav/Settings Elements
var langSelect = document.getElementById('langSelect');
var modelSelect = document.getElementById('modelSelect');
var envSelect = document.getElementById('envSelect');

// Tabs
var navTabs = document.querySelectorAll('.nav-tab');
var viewPanels = document.querySelectorAll('.view-panel');

